# app/assistant_engine.py
import os
import json
import sys
from typing import TypedDict, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage 
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
import pyodbc 
import re
from datetime import datetime, date # Ensure date is imported

# --- Conditional Import for schema_index ---
if __name__ == "__main__" and __package__ is None:
    current_script_path = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(current_script_path))
    if project_root not in sys.path: sys.path.insert(0, project_root)
    from app.schema_index import query_schema, SCHEMA_COLLECTION_NAME
    import chromadb 
else:
    from .schema_index import query_schema, SCHEMA_COLLECTION_NAME

# --- Environment Setup ---
from dotenv import load_dotenv
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
load_dotenv(dotenv_path=dotenv_path)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DB_DRIVER = os.environ.get("DB_DRIVER"); DB_SERVER = os.environ.get("DB_SERVER"); DB_NAME = os.environ.get("DB_NAME")
DB_USER = os.environ.get("DB_USER"); DB_PASSWORD = os.environ.get("DB_PASSWORD")
db_connection_string = None
if all([DB_DRIVER, DB_SERVER, DB_NAME]):
    conn_str_parts = [f"DRIVER={DB_DRIVER}", f"SERVER={DB_SERVER}", f"DATABASE={DB_NAME}"]
    if DB_USER: conn_str_parts.extend([f"UID={DB_USER}", f"PWD={DB_PASSWORD}"])
    else: conn_str_parts.append("Trusted_Connection=yes")
    db_connection_string = ";".join(conn_str_parts)
else: print("Warning: DB connection details not fully configured.")
llm = ChatOpenAI(model="gpt-4", temperature=0, openai_api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
if not llm: print("Warning: LLM not initialized.")

# --- GraphState definition ---
class GraphState(TypedDict):
    original_query: str
    cleaned_query: Optional[str]
    requested_chart_type: Optional[str] 
    retrieved_schema_parts: Optional[List[str]]
    generated_sql: Optional[str]
    sql_query_result: Optional[List[Dict[str, Any]]]
    analysis_summary: Optional[str] 
    chart_json: Optional[Dict[str, Any]] 
    table_data: Optional[Dict[str, Any]] 
    error_message: Optional[str] 
    follow_up_context: Optional[List[BaseMessage]]

# --- Helper Functions for Analyzer ---
def is_numeric(value):
    if value is None: return False
    return isinstance(value, (int, float))

def is_date_like(column_name_or_value):
    if isinstance(column_name_or_value, str):
        name = column_name_or_value.lower()
        if any(term in name for term in ["date", "year", "month", "time", "dt", "period"]): return True
        if re.match(r"^\d{4}(-\d{2}(-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?Z?)?)?)?)?$", column_name_or_value): return True
    elif isinstance(column_name_or_value, (datetime, date)):
        return True
    return False

def get_column_types(query_result: List[Dict[str, Any]], headers: List[str]):
    col_types = {}
    if not query_result: return col_types
    sample_row = query_result[0] 
    for header in headers:
        value = sample_row.get(header)
        is_strictly_numeric_col = True
        for row in query_result:
            val_in_col = row.get(header)
            if val_in_col is not None and not is_numeric(val_in_col):
                is_strictly_numeric_col = False; break
        is_date_col_by_name = is_date_like(header)
        # Check if first value looks like a date, and if so, check a few more for consistency
        is_date_col_by_value = False
        if not is_date_col_by_name and isinstance(value, str) and is_date_like(value):
            # Check a sample of rows to confirm date-like nature if name doesn't indicate it
            date_like_count = 0
            for i, row_check in enumerate(query_result):
                if i >= 5: break # Check up to 5 rows
                if is_date_like(str(row_check.get(header,""))): date_like_count +=1
            if date_like_count >= min(3, len(query_result)): # If at least 3 or all (if less than 3) are date-like
                 is_date_col_by_value = True
        
        is_year_col_by_name = "year" in header.lower() and is_strictly_numeric_col and \
                              all(1900 < int(row.get(header) or 0) < 2100 for row in query_result if row.get(header) is not None and isinstance(row.get(header), (int, float)))


        if is_year_col_by_name: col_types[header] = "categorical_year" # Treat year as categorical for grouping
        elif is_strictly_numeric_col: col_types[header] = "numeric"
        elif is_date_col_by_name or is_date_col_by_value : col_types[header] = "date_like"
        else: col_types[header] = "categorical"
    return col_types

# --- Node Implementations ---
def intent_detection_node(state: GraphState) -> GraphState:
    print("--- Running Intent Detection Node ---")
    query_lower = state.get("original_query","").lower()
    state["cleaned_query"] = state.get("original_query","") 
    requested_type = None
    if "pie chart" in query_lower or "pie char" in query_lower: requested_type = "pie" # Catch "pie char"
    elif "donut chart" in query_lower: requested_type = "doughnut"
    elif "line chart" in query_lower or "line graph" in query_lower or "trend" in query_lower: requested_type = "line"
    elif "area chart" in query_lower: requested_type = "line" 
    elif "bar chart" in query_lower or "bar graph" in query_lower: requested_type = "bar"
    elif "horizontal bar" in query_lower: requested_type = "bar" 
    elif "scatter plot" in query_lower: requested_type = "scatter"
    # ... (other chart types)
    state["requested_chart_type"] = requested_type
    print(f"Cleaned Query: {state['cleaned_query']}, Requested Chart Type: {requested_type}")
    return state

def schema_retriever_node(state: GraphState) -> GraphState:
    # (No changes from previous version: assistant_engine_py_v12_final_refinements)
    print("--- Running Schema Retriever Node ---")
    query = state.get("cleaned_query")
    if not query: state["error_message"] = "No query to schema retriever."; state["retrieved_schema_parts"] = []; return state
    retrieved_parts = []
    try:
        print(f"Querying ChromaDB for: '{query}'")
        schema_results = query_schema(query_texts=[query], n_results=12, collection_name=SCHEMA_COLLECTION_NAME) 
        if schema_results and schema_results.get("documents"):
            for doc_list in schema_results["documents"]: retrieved_parts.extend(doc_list) 
        if not retrieved_parts:
            print(f"No specific schema parts found. Trying generic query.")
            generic_schema_info = query_schema(query_texts=["overview of all tables and their primary purpose"], n_results=7, collection_name=SCHEMA_COLLECTION_NAME)
            if generic_schema_info and generic_schema_info.get("documents"):
                 for doc_list in generic_schema_info["documents"]: retrieved_parts.extend(doc_list)
        state["retrieved_schema_parts"] = list(set(retrieved_parts))
        print(f"Retrieved {len(state['retrieved_schema_parts'])} unique schema parts:")
        if state["retrieved_schema_parts"]:
            for i, part in enumerate(state["retrieved_schema_parts"]): print(f"  Part {i+1}: {part[:150]}...")
        else: print("  No schema parts retrieved.")
    except Exception as e:
        state["error_message"] = f"Error in schema_retriever_node: {str(e)}"; state["retrieved_schema_parts"] = []
    return state

def sql_generator_node(state: GraphState) -> GraphState:
    # (No changes from previous version: assistant_engine_py_v12_final_refinements)
    print("--- Running SQL Generator Node ---")
    user_query = state.get("cleaned_query"); schema_parts = state.get("retrieved_schema_parts"); conversation_history = state.get("follow_up_context", []) 
    if not user_query: state["error_message"] = "User query missing."; state["generated_sql"] = None; return state
    if not llm: state["error_message"] = "LLM not available."; state["generated_sql"] = None; return state
    schema_context_for_prompt = "\n".join(schema_parts) if schema_parts else "No specific schema context. Infer table/column names (e.g., OTM.SHIPMENT). If unsure, output 'NO_QUERY'."
    history_for_prompt = ""
    if conversation_history:
        history_for_prompt = "Previous Conversation Turn(s):\n"; 
        for msg in conversation_history: history_for_prompt += f"{'User' if isinstance(msg, HumanMessage) else 'Assistant'}: {msg.content}\n"
        history_for_prompt += "------------------------\n"
    system_prompt_template = """
You are an expert SQL generator specializing in SQL Server syntax for an Oracle Transportation Management (OTM) database.
Your task is to generate a single, valid SQL Server query based on the user's current question, the provided database schema context, AND THE PREVIOUS CONVERSATION TURN(S) if available.
The previous conversation provides context for follow-up questions.
Guidelines:
1. ONLY output the SQL query. Do not include any explanations or other text.
2. If you cannot confidently generate a query, output ONLY the string "NO_QUERY".
3. Use the provided schema context (table/column names, descriptions, types, relationships) and conversation history.
4. Prioritize using column names explicitly mentioned and described in the schema context. Do not invent column names.
5. When a query involves dates, carefully examine COLUMN_DESCRIPTION of available date-type columns to select the most semantically appropriate one, considering the conversation history for context.
6. All table names in the OTM database are likely prefixed with 'OTM.' (e.g., `OTM.SHIPMENT`). Ensure your query uses this prefix.
7. Select only necessary columns. Avoid `SELECT *`.
8. Ensure SQL syntax is SQL Server compatible (e.g., `TOP N`, `YEAR(date_column)`). Queries may use Common Table Expressions (CTEs) starting with `WITH`.
9. For aggregations, use meaningful aliases (e.g., `COUNT(*) AS TotalCount`).
10. Only SELECT queries (which can include CTEs starting with WITH) are allowed. No DML/DDL.
11. If context is insufficient, output "NO_QUERY".
12. Never respond with any key like 'GID', 'XID' etc. instead join with respected table and provide the name, hide our database structure from the end user, maintain proper abstraction.
13. Hide sensitive information like 'GID', 'XID', etc. from the end user. Instead, join with the respective table and provide the name, maintaining proper abstraction.
15. If you need to join the same table multiple times for different roles (e.g., joining OTM.LOCATION for both an origin and a destination), YOU MUST use different table aliases for each instance of the table in the JOIN (e.g., `... JOIN OTM.LOCATION OriginLoc ON S.SOURCE_LOCATION_GID = OriginLoc.LOCATION_GID JOIN OTM.LOCATION DestLoc ON S.DEST_LOCATION_GID = DestLoc.LOCATION_GID ...`). Refer to columns using these aliases (e.g., `OriginLoc.LOCATION_NAME`, `DestLoc.LOCATION_NAME`).
"""
    human_prompt_template = f"""{history_for_prompt}
Database Schema Context:
------------------------
{schema_context_for_prompt}
------------------------
User's Current Question:
----------------
{user_query}
------------------------
Based on the schema, conversation history, and the user's current question, generate the SQL Server query:
"""
    langchain_messages = [ SystemMessage(content=system_prompt_template.strip()), HumanMessage(content=human_prompt_template.strip()) ]
    try:
        print("Invoking LLM for SQL generation (with history)...")
        response = llm.invoke(langchain_messages)
        generated_sql_raw = response.content.strip()
        print(f"LLM Raw Response: '{generated_sql_raw}'")
        if not generated_sql_raw or "NO_QUERY" in generated_sql_raw.upper():
            error_msg = f"I couldn't construct a specific SQL query for: '{user_query}'. The schema or context might be insufficient." if "NO_QUERY" in generated_sql_raw.upper() else "Could not generate SQL."
            print("LLM indicated no query or invalid response."); state["error_message"] = error_msg; state["generated_sql"] = None
        else:
            cleaned_sql = generated_sql_raw.replace("```sql", "").replace("```", "").strip()
            sql_upper_stripped = cleaned_sql.upper().strip()
            if not (sql_upper_stripped.startswith("SELECT") or sql_upper_stripped.startswith("WITH")):
                print(f"Warning: Generated query not SELECT/WITH: {cleaned_sql}"); state["error_message"] = "Generated query isn't SELECT or WITH."; state["generated_sql"] = None
            else: state["generated_sql"] = cleaned_sql; state["error_message"] = None 
    except Exception as e:
        print(f"Error during LLM call for SQL generation: {e}"); state["error_message"] = f"Error generating SQL: {str(e)}"; state["generated_sql"] = None
    print(f"Generated SQL: {state['generated_sql']}")
    return state

def sql_executor_node(state: GraphState) -> GraphState:
    # (No changes from previous version: assistant_engine_py_v12_final_refinements)
    print("--- Running SQL Executor Node ---")
    sql_query = state.get("generated_sql")
    if not sql_query or "NO_QUERY" in sql_query.upper() or sql_query.startswith("-- Mock SQL for query:"):
        if not state.get("error_message"): state["error_message"] = "No valid SQL query to execute."
        print(f"SQL Execution Skipped. Reason: {state.get('error_message', 'No valid SQL.')}"); state["sql_query_result"] = None; return state
    if not db_connection_string:
        state["error_message"] = "DB connection string not configured."; print(f"Error: {state['error_message']}"); state["sql_query_result"] = None; return state
    print(f"Executing SQL: {sql_query}")
    results = []
    conn = None
    try:
        conn = pyodbc.connect(db_connection_string)
        cursor = conn.cursor()
        cursor.execute(sql_query)
        if cursor.description:
            columns = [column[0] for column in cursor.description]
            for row in cursor.fetchall(): results.append(dict(zip(columns, row)))
        else: 
            raw_rows = cursor.fetchall()
            if raw_rows:
                if len(raw_rows) == 1 and len(raw_rows[0]) == 1: results = [{"AGGREGATE_RESULT": raw_rows[0][0]}]; print("Query returned single aggregate value.")
                else: print("Query returned no column descriptions, unexpected format."); results = [{"raw_data": r} for r in raw_rows]
        state["sql_query_result"] = results; state["error_message"] = None 
        print(f"SQL executed. Rows: {len(results)}")
        if 0 < len(results) < 5: print(f"Sample: {results[:5]}")
        elif len(results) == 0: print("Query returned no results."); state["analysis_summary"] = "The query was successful, but no matching records were found."
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]; db_err_msg = str(ex)
        print(f"SQL Error. SQLSTATE: {sqlstate}. Msg: {db_err_msg}")
        state["error_message"] = f"There was an error querying the database: {db_err_msg}"; state["sql_query_result"] = None
    except Exception as e:
        print(f"Unexpected SQL execution error: {e}")
        state["error_message"] = f"An unexpected error occurred during data retrieval: {str(e)}"; state["sql_query_result"] = None
    finally:
        if conn: conn.close(); print("DB connection closed.")
    return state


def analyzer_visualizer_node(state: GraphState) -> GraphState: # UPDATED
    print("--- Running Analyzer/Visualizer Node ---")
    query_result = state.get("sql_query_result")
    original_query = state.get("original_query","").lower()
    requested_chart_type = state.get("requested_chart_type") 
    
    analysis_summary = state.get("analysis_summary") 
    chart_config = None
    table_config = None
    
    default_chart_title = f"Data for: '{state.get('original_query')}'" 

    if state.get("error_message") and not query_result:
        analysis_summary = None 
    elif not query_result: 
        if not analysis_summary: analysis_summary = "No data found for your query."
    else: 
        if isinstance(query_result, list) and len(query_result) > 0:
            headers = list(query_result[0].keys())
            num_rows = len(query_result)
            
            rows_for_table = [[str(row.get(h, '')) for h in headers] for row in query_result]
            table_config = {"headers": headers, "rows": rows_for_table}

            col_types_map = get_column_types(query_result, headers)
            numeric_cols = [h for h, t in col_types_map.items() if t == "numeric"]
            categorical_cols = [h for h, t in col_types_map.items() if t == "categorical" or t == "categorical_year"] # Treat year as cat
            date_like_cols = [h for h, t in col_types_map.items() if t == "date_like"] # True date/datetime
            
            final_chart_type_to_render = requested_chart_type 
            
            chart_options = {
                "responsive": True, "maintainAspectRatio": False,
                "plugins": { 
                    "legend": {"display": True, "position": "top"}, 
                    "title": {"display": True, "text": default_chart_title} 
                }
            }
            
            # 1. Single Value / KPI Display
            if num_rows == 1 and len(headers) == 1 and numeric_cols:
                kpi_value = query_result[0][numeric_cols[0]]
                kpi_title_header = headers[0].replace("_", " ").title()
                analysis_summary = f"The {kpi_title_header} is: {kpi_value if kpi_value is not None else 'N/A'}."
                final_chart_type_to_render = None 
            
            # 2. Time Series (Line/Area chart)
            #    Data: One 'date_like' or 'categorical_year' (+ 'Month' if present) column, one or more numeric columns.
            elif ( (len(date_like_cols) == 1 and len(numeric_cols) >= 1) or \
                   ('Year' in headers and 'Month' in headers and len(numeric_cols) >= 1) or \
                   (len(categorical_cols) == 1 and "year" in categorical_cols[0].lower() and len(numeric_cols) >=1 ) ):
                
                labels = []
                date_col_display_name = "Time"
                sorted_query_result = query_result # Default

                if 'Year' in headers and 'Month' in headers:
                    temp_data_for_sort = [{'year': int(row.get('Year',0)), 'month': int(row.get('Month',0)), 'data': row} for row in query_result]
                    sorted_query_result_by_time = sorted(temp_data_for_sort, key=lambda x: (x['year'], x['month']))
                    sorted_query_result = [item['data'] for item in sorted_query_result_by_time]
                    labels = [f"{row.get('Year', '')}-{str(row.get('Month', '')).zfill(2)}" for row in sorted_query_result]
                    date_col_display_name = "Year-Month"
                elif date_like_cols: # Single actual date column
                    date_col_for_labels = date_like_cols[0]
                    try: sorted_query_result = sorted(query_result, key=lambda x: str(x.get(date_col_for_labels, "")))
                    except TypeError: pass # Already sorted or unsorTable
                    labels = [str(row.get(date_col_for_labels)) for row in sorted_query_result]
                    date_col_display_name = date_col_for_labels.replace('_',' ').title()
                elif categorical_cols and "year" in categorical_cols[0].lower(): # Year as category
                    date_col_for_labels = categorical_cols[0]
                    try: sorted_query_result = sorted(query_result, key=lambda x: str(x.get(date_col_for_labels, "")))
                    except TypeError: pass
                    labels = [str(row.get(date_col_for_labels)) for row in sorted_query_result]
                    date_col_display_name = date_col_for_labels.replace('_',' ').title()


                datasets = []
                line_chart_colors = ['rgb(75, 192, 192)', 'rgb(255, 99, 132)', 'rgb(54, 162, 235)', 'rgb(255, 206, 86)']
                
                for i, num_col in enumerate(numeric_cols[:len(line_chart_colors)]): # Consider all numeric cols found
                    try:
                        data_values = [float(row.get(num_col) or 0) for row in sorted_query_result]
                        datasets.append({ "label": num_col.replace("_", " ").title(), "data": data_values, "fill": False, "borderColor": line_chart_colors[i % len(line_chart_colors)], "tension": 0.1 })
                    except (ValueError, TypeError) as e: print(f"Warning: Skipping numeric column {num_col} for line chart: {e}"); continue
                
                if datasets:
                    if not final_chart_type_to_render or final_chart_type_to_render not in ["line", "area"]:
                        final_chart_type_to_render = "line"
                    
                    is_area_requested = "area" in original_query
                    if (final_chart_type_to_render == "area" or is_area_requested) and len(datasets)==1: datasets[0]["fill"] = True; final_chart_type_to_render = "line"
                    elif (final_chart_type_to_render == "area" or is_area_requested) and len(datasets)>1: final_chart_type_to_render = "line"

                    chart_options["plugins"]["title"]["text"] = f"{datasets[0]['label']}{' & others' if len(datasets)>1 else ''} Trend over {date_col_display_name}"
                    if len(datasets) == 1: chart_options["plugins"]["legend"]["display"] = False
                    
                    chart_config = {"type": "line", "data": {"labels": labels, "datasets": datasets}, "options": chart_options}
                    analysis_summary = chart_options["plugins"]["title"]["text"] 

            # 3. Categorical vs Numerical (Pie/Doughnut/Bar)
            elif len(categorical_cols) == 1 and len(numeric_cols) == 1 and not chart_config:
                cat_col = categorical_cols[0]; num_col = numeric_cols[0]
                labels = [str(row.get(cat_col)) for row in query_result]
                try:
                    data_values = [float(row.get(num_col) or 0) for row in query_result]
                    chart_options["plugins"]["title"]["text"] = f"{num_col.replace('_',' ').title()} by {cat_col.replace('_',' ').title()}"
                    
                    if final_chart_type_to_render in ["pie", "doughnut"] or \
                       (not final_chart_type_to_render and num_rows <= 7 and num_rows > 1): # Heuristic for pie
                        final_chart_type_to_render = final_chart_type_to_render if final_chart_type_to_render in ["pie", "doughnut"] else "pie"
                        chart_config = {"type": final_chart_type_to_render, "data": {"labels": labels, "datasets": [{"label": num_col.replace("_", " ").title(), "data": data_values, "backgroundColor": ['rgba(255,99,132,0.7)','rgba(54,162,235,0.7)','rgba(255,206,86,0.7)','rgba(75,192,192,0.7)','rgba(153,102,255,0.7)','rgba(255,159,64,0.7)']}]}, "options": chart_options}
                    elif num_rows > 0: 
                        final_chart_type_to_render = "bar" 
                        chart_options["plugins"]["legend"]["display"] = False
                        if "horizontal bar" in original_query and requested_chart_type == "bar" : chart_options["indexAxis"] = 'y'
                        chart_config = {"type": "bar", "data": {"labels": labels, "datasets": [{"label": num_col.replace("_", " ").title(), "data": data_values, "backgroundColor": 'rgba(75, 192, 192, 0.7)' if chart_options.get("indexAxis") != 'y' else 'rgba(54, 162, 235, 0.7)'}]}, "options": chart_options}
                    
                    if chart_config: analysis_summary = chart_options["plugins"]["title"]["text"] 
                except (ValueError, TypeError) as e: print(f"Warning: Could not process cat/num chart: {e}")
            
            # 4. Two Categorical + One Numeric (e.g., Source, Dest, Count)
            elif len(categorical_cols) >= 2 and len(numeric_cols) == 1 and not chart_config:
                cat_col1 = categorical_cols[0]; cat_col2 = categorical_cols[1]; num_col = numeric_cols[0]
                chart_title_text = f"{num_col.replace('_',' ').title()} by {cat_col1.replace('_',' ').title()} & {cat_col2.replace('_',' ').title()}"
                chart_options["plugins"]["title"]["text"] = chart_title_text
                analysis_summary = chart_title_text 

                if requested_chart_type == "pie" and num_rows <= 10 and num_rows > 1:
                    combined_labels_map = {}
                    for row in query_result:
                        label = f"{str(row.get(cat_col1, 'N/A'))[:15]} - {str(row.get(cat_col2, 'N/A'))[:15]}"
                        combined_labels_map[label] = combined_labels_map.get(label, 0) + float(row.get(num_col) or 0)
                    labels = list(combined_labels_map.keys()); data_values = list(combined_labels_map.values())
                    if len(labels) <=10 : 
                        chart_config = {"type": "pie", "data": {"labels": labels, "datasets": [{"data": data_values, "backgroundColor": ['rgba(255,99,132,0.7)','rgba(54,162,235,0.7)','rgba(255,206,86,0.7)','rgba(75,192,192,0.7)','rgba(153,102,255,0.7)']}]}, "options": chart_options}
                        analysis_summary = f"Pie chart: {chart_options['plugins']['title']['text']}"
                    else:
                        analysis_summary = f"Data for '{chart_options['plugins']['title']['text']}' retrieved. A pie chart is not suitable for {len(labels)} categories. Showing table."
                        chart_config = None
                elif (requested_chart_type == "bar" or not requested_chart_type) and num_rows > 0 and num_rows <= 20 :
                    labels = [f"{str(row.get(cat_col1, 'N/A'))[:15]} - {str(row.get(cat_col2, 'N/A'))[:15]}" for row in query_result]
                    try:
                        data_values = [float(row.get(num_col) or 0) for row in query_result]
                        chart_options["plugins"]["legend"]["display"] = False
                        chart_config = {"type":"bar", "data":{"labels":labels, "datasets":[{"label":num_col.replace('_',' ').title(), "data":data_values, "backgroundColor": 'rgba(54, 162, 235, 0.7)'}]}, "options":chart_options}
                        analysis_summary = f"Bar chart: {chart_options['plugins']['title']['text']}"
                    except (ValueError, TypeError) as e:
                        analysis_summary = f"Data for '{chart_options['plugins']['title']['text']}' retrieved, bar chart error: {e}"; chart_config = None
                else: 
                    analysis_summary = f"Displaying top results for {chart_options['plugins']['title']['text'].lower()}."
                    chart_config = None 

            # 5. Two Numerics (Scatter)
            elif len(numeric_cols) >= 2 and not chart_config:
                num_col_x = numeric_cols[0]; num_col_y = numeric_cols[1]
                try:
                    scatter_data = [{"x": float(row.get(num_col_x) or 0), "y": float(row.get(num_col_y) or 0)} for row in query_result]
                    if scatter_data:
                        final_chart_type_to_render = requested_chart_type if requested_chart_type == "scatter" else "scatter"
                        chart_options["plugins"]["title"]["text"] = f"Relationship: {num_col_x.replace('_',' ').title()} vs {num_col_y.replace('_',' ').title()}"
                        chart_options["plugins"]["legend"]["display"] = False
                        chart_options["scales"] = {"x": {"title": {"display": True, "text": num_col_x.replace('_',' ').title()}}, "y": {"title": {"display": True, "text": num_col_y.replace('_',' ').title()}}}
                        chart_config = {"type": final_chart_type_to_render, "data": {"datasets": [{"label": chart_options["plugins"]["title"]["text"], "data": scatter_data, "backgroundColor": 'rgba(255, 99, 132, 0.7)'}]}, "options": chart_options}
                        analysis_summary = chart_options["plugins"]["title"]["text"] 
                except (ValueError, TypeError) as e: print(f"Warning: Could not process data for scatter plot: {e}")
            
            # Fallback summary if no chart created and summary is still generic
            if not chart_config and (analysis_summary is None or "records for" in analysis_summary.lower() or "found" in analysis_summary.lower()):
                analysis_summary = f"Here's the data for your query regarding '{state.get('original_query')}':"

    state["analysis_summary"] = analysis_summary
    state["chart_json"] = chart_config 
    state["table_data"] = table_config
    print(f"Final Analysis Summary for UI: {state['analysis_summary']}")
    if chart_config: print(f"Chart JSON generated (type: {chart_config.get('type')}). Title: {chart_config.get('options',{}).get('plugins',{}).get('title',{}).get('text')}")
    if table_config: print("Table data generated.")
    return state

# response_formatter_node and get_assistant_response
def response_formatter_node(state: GraphState) -> GraphState:
    print("--- Running Response Formatter Node ---")
    current_summary = state.get("analysis_summary"); error_msg = state.get("error_message")
    if error_msg:
        if not current_summary or current_summary.startswith("I couldn't construct a specific SQL query") or "found" in current_summary.lower() or "processed" in current_summary.lower(): 
            state["analysis_summary"] = error_msg 
        elif error_msg not in current_summary : 
            state["analysis_summary"] = f"An error occurred: {error_msg}. {current_summary if current_summary else ''}"
    if not state.get("analysis_summary"): state["analysis_summary"] = "Request processed."
    return state

def get_assistant_response(user_query: str, conversation_history_raw: Optional[List[Dict[str,str]]] = None) -> Dict:
    if not OPENAI_API_KEY or not llm: return { "answer": "Error: LLM not configured.", "chart": None, "raw_table": None, "id": f"error_no_llm_{os.urandom(4).hex()}" }
    langchain_history: List[BaseMessage] = []
    if conversation_history_raw:
        for item in conversation_history_raw:
            if item.get("role") == "user": langchain_history.append(HumanMessage(content=item.get("content","")))
            elif item.get("role") == "assistant": langchain_history.append(AIMessage(content=item.get("content","")))
    initial_state = GraphState( original_query=user_query, cleaned_query=None, requested_chart_type=None, retrieved_schema_parts=None, generated_sql=None, sql_query_result=None, analysis_summary=None, chart_json=None, table_data=None, error_message=None, follow_up_context=langchain_history )
    print(f"\nInvoking graph for query: '{user_query}' with {len(langchain_history)} history messages.")
    final_state = app_graph.invoke(initial_state)
    print(f"Graph complete. Summary: '{final_state.get('analysis_summary')}', SQL: {final_state.get('generated_sql')}, Chart: {'Yes' if final_state.get('chart_json') else 'No'}")
    
    response_answer = final_state.get("analysis_summary") 

    # If a chart is present, analysis_summary from analyzer_visualizer should be a good title/explanation.
    # If no chart, but table, and summary is too generic, make it more direct.
    if not final_state.get("chart_json") and final_state.get("table_data") and \
       (response_answer is None or "found" in response_answer.lower() or "processed" in response_answer.lower() or "retrieved" in response_answer.lower() or "data for" in response_answer.lower()):
        response_answer = f"Here's the data for your query: '{final_state.get('original_query')}'"
    elif final_state.get("error_message") and (response_answer is None or final_state.get("error_message","") not in response_answer):
        response_answer = final_state.get("error_message")
    elif not response_answer: 
        if final_state.get("generated_sql") and final_state.get("generated_sql").upper() == "NO_QUERY": 
            response_answer = f"I understood your query: '{final_state.get('original_query')}', but I couldn't form a specific data query."
        else: response_answer = "I've processed your request. No specific data to display."

    response = {
        "answer": response_answer, 
        "chart": final_state.get("chart_json"), 
        "raw_table": final_state.get("table_data"),
        "id": f"insight_{user_query[:20].replace(' ', '_').replace('?', '').replace("'", "")}_{os.urandom(4).hex()}" 
    }
    return response

# --- Build the Graph & Main test block (remains the same) ---
workflow = StateGraph(GraphState)
workflow.add_node("intent_detection", intent_detection_node); workflow.add_node("schema_retriever", schema_retriever_node); workflow.add_node("sql_generator", sql_generator_node); workflow.add_node("sql_executor", sql_executor_node); workflow.add_node("analyzer_visualizer", analyzer_visualizer_node); workflow.add_node("response_formatter", response_formatter_node)
workflow.add_edge("intent_detection", "schema_retriever"); workflow.add_edge("schema_retriever", "sql_generator"); workflow.add_edge("sql_generator", "sql_executor"); workflow.add_edge("sql_executor", "analyzer_visualizer"); workflow.add_edge("analyzer_visualizer", "response_formatter"); workflow.add_edge("response_formatter", END)
workflow.set_entry_point("intent_detection")
app_graph = workflow.compile()

if __name__ == '__main__':
    print("Testing Assistant Engine...")
    current_dir = os.path.dirname(os.path.abspath(__file__)); project_root_path = os.path.dirname(current_dir)
    chroma_data_path_for_test = os.path.join(project_root_path, "chroma_data")
    schema_collection_name_for_test = SCHEMA_COLLECTION_NAME if 'SCHEMA_COLLECTION_NAME' in globals() else "logistics_schema_csv_v1"
    try:
        if 'chromadb' not in globals(): import chromadb 
        chroma_client_test = chromadb.PersistentClient(path=chroma_data_path_for_test)
        test_collection = chroma_client_test.get_collection(name=schema_collection_name_for_test)
        if test_collection.count() == 0: print(f"\nWARNING: ChromaDB collection '{schema_collection_name_for_test}' is empty. Run schema_index.py.\n")
        else: print(f"\nChromaDB collection '{schema_collection_name_for_test}' found with {test_collection.count()} documents.\n")
    except Exception as e: print(f"\nCould not verify ChromaDB collection '{schema_collection_name_for_test}': {e}. Run schema_index.py.\n")
    print(f"Test DB Connection String: {db_connection_string if db_connection_string else 'NOT CONFIGURED'}")
    history_example = [{"role": "user", "content": "What was the total shipment cost last year using START_TIME?"},{"role": "assistant", "content": "The total shipment cost last year was $125,000."}]
    test_queries_with_history = [ 
        ({"query": "What is the total shipment count?", "history": []}),
        ({"query": "Show me shipment count by year using START_TIME as a line chart", "history": []}),
        ({"query": "What are the top 5 shipment counts by source location name and destination location name in a pie chart?", "history": []}),
        ({"query": "And what about for the year before that?", "history": history_example}) 
    ]
    print("\n--- Testing Assistant Engine ---")
    for i, test_case in enumerate(test_queries_with_history):
        print(f"\n--- Invoking graph for query {i+1}: '{test_case['query']}' ---")
        response = get_assistant_response(test_case['query'], conversation_history_raw=test_case['history'])
        print(f"\n--- Final Response for Query {i+1} ---"); print(json.dumps(response, indent=2))