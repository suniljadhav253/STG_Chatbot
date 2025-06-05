# project_root/app/schema_index.py
import chromadb
import os
import pandas as pd

# --- Configuration ---
# Path to your schema CSV file (relative to project_root)
SCHEMA_CSV_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "schema2.csv") 

CHROMA_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "chroma_data")
os.makedirs(CHROMA_DATA_PATH, exist_ok=True) # Ensure the directory exists

client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)
SCHEMA_COLLECTION_NAME = "logistics_schema_csv_v1" # Changed collection name for clarity

# Optional: OpenAI embeddings (ensure OPENAI_API_KEY is set in .env)
# from dotenv import load_dotenv
# from chromadb.utils import embedding_functions
# load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
# openai_ef = embedding_functions.OpenAIEmbeddingFunction(
# api_key=os.environ.get("OPENAI_API_KEY"),
# model_name="text-embedding-ada-002"
# )

def load_schema_from_csv(csv_path):
    """
    Loads schema information from a CSV file and restructures it.
    Expected CSV columns: mainTableName, COLUMN_NAME, DATA_TYPE, 
                           referenceTableName, refColumnName
                           (Optional: TABLE_DESCRIPTION, COLUMN_DESCRIPTION)
    """
    try:
        df = pd.read_csv(csv_path)
        # Replace NaN or NULL-like strings in reference columns with None for easier handling
        df['referenceTableName'] = df['referenceTableName'].replace(['NULL', 'Null', 'null', float('nan')], None)
        df['refColumnName'] = df['refColumnName'].replace(['NULL', 'Null', 'null', float('nan')], None)

    except FileNotFoundError:
        print(f"Error: Schema CSV file not found at {csv_path}")
        return None
    except Exception as e:
        print(f"Error reading schema CSV: {e}")
        return None

    tables_data = {}
    for _, row in df.iterrows():
        table_name = row['mainTableName']
        if table_name not in tables_data:
            tables_data[table_name] = {
                "name": table_name,
                # Check if TABLE_DESCRIPTION column exists in CSV, otherwise default
                "description": row.get('TABLE_DESCRIPTION', f"Table containing {table_name.lower()} data."), 
                "columns": []
            }
        
        column_info = {
            "name": row['COLUMN_NAME'],
            "type": row['DATA_TYPE'],
            # Check if COLUMN_DESCRIPTION column exists, otherwise default
            "description": row.get('COLUMN_DESCRIPTION', f"Column named {row['COLUMN_NAME']}."),
            "primary_key": False, # Assuming CSV doesn't directly state PK. This might need adjustment.
                                  # Or you can add a 'IS_PRIMARY_KEY' column to your CSV.
            "foreign_key": None
        }

        if pd.notna(row['referenceTableName']) and pd.notna(row['refColumnName']):
            column_info["foreign_key"] = {
                "references_table": row['referenceTableName'],
                "references_column": row['refColumnName']
            }
        
        # A simple heuristic for primary keys (e.g., if column name ends with ID or SEQ_NO)
        # This is just an example; a dedicated column in CSV is better.
        if row['COLUMN_NAME'].upper().endswith('ID') or row['COLUMN_NAME'].upper().endswith('SEQ_NO'):
             # To avoid marking all IDs as PK if it's a FK, check if it's already an FK
            if not column_info["foreign_key"] or column_info["foreign_key"]["references_table"] != table_name : # crude check
                 column_info["primary_key"] = True


        tables_data[table_name]["columns"].append(column_info)
    
    # Convert the dictionary of tables into a list format similar to LOGISTICS_SCHEMA
    schema_structure = {"tables": list(tables_data.values())}
    return schema_structure

def create_schema_documents_from_structure(schema_data):
    """
    Creates text documents from the restructured schema data (from CSV).
    """
    documents = []
    metadatas = []
    ids = []
    doc_id_counter = 1

    if not schema_data or not schema_data.get("tables"):
        print("No table data found in the processed schema structure.")
        return [], [], []

    for table in schema_data.get("tables", []):
        table_name = table.get("name")
        table_description = table.get("description", f"Table: {table_name}") # Default description

        # Document for the table itself
        table_doc_content = f"Table: {table_name}. Description: {table_description}."
        col_descs_for_table_doc = []
        for col in table.get("columns", []):
            col_info = f"Column: {col.get('name')} (Type: {col.get('type')}). Description: {col.get('description', '')}"
            if col.get('primary_key'):
                col_info += " This is a primary key."
            if col.get('foreign_key'):
                fk = col.get('foreign_key')
                col_info += f" This is a foreign key referencing {fk.get('references_table')}({fk.get('references_column')})."
            col_descs_for_table_doc.append(col_info)
        
        if col_descs_for_table_doc:
            table_doc_content += " Columns include: " + " | ".join(col_descs_for_table_doc)

        documents.append(table_doc_content)
        metadatas.append({"type": "table", "table_name": table_name, "source": "csv_schema"})
        ids.append(f"table_{table_name.lower().replace(' ', '_')}_{doc_id_counter}")
        doc_id_counter += 1

        # Individual documents for each column
        for column in table.get("columns", []):
            col_name = column.get("name")
            col_type = column.get("type")
            col_description = column.get("description", f"Column {col_name} in table {table_name}") # Default
            
            col_doc_content = f"Table: {table_name}, Column: {col_name}. Type: {col_type}. Description: {col_description}."
            if column.get("primary_key"):
                col_doc_content += " This column is a primary key."
            if column.get("foreign_key"):
                fk_info = column.get("foreign_key")
                col_doc_content += f" This column is a foreign key referencing table {fk_info['references_table']}, column {fk_info['references_column']}."
            
            documents.append(col_doc_content)
            metadatas.append({
                "type": "column", 
                "table_name": table_name, 
                "column_name": col_name,
                "source": "csv_schema"
            })
            ids.append(f"col_{table_name.lower().replace(' ', '_')}_{col_name.lower().replace(' ', '_')}_{doc_id_counter}")
            doc_id_counter += 1
            
    return documents, metadatas, ids

def index_schema(collection_name=SCHEMA_COLLECTION_NAME, csv_path=SCHEMA_CSV_FILE_PATH):
    """
    Initializes ChromaDB, loads schema from CSV, and indexes schema documents.
    """
    print(f"Initializing ChromaDB client with persistence at: {CHROMA_DATA_PATH}")
    
    # Determine embedding function
    # current_embedding_function = openai_ef if "openai_ef" in globals() else None
    # if current_embedding_function:
    #     print("Using OpenAI embeddings.")
    #     collection = client.get_or_create_collection(name=collection_name, embedding_function=current_embedding_function)
    # else:
    print("Using default ChromaDB embeddings (Sentence Transformers).")
    collection = client.get_or_create_collection(name=collection_name)
    
    print(f"Using collection: '{collection_name}'")

    print("Clearing existing collection (if any) and re-indexing schema for development...")
    try:
        client.delete_collection(name=collection_name)
    except Exception as e:
        print(f"Note: Could not delete collection (it might not exist yet): {e}")
    
    # Recreate the collection (with specific embedding function if chosen)
    # if current_embedding_function:
    #    collection = client.get_or_create_collection(name=collection_name, embedding_function=current_embedding_function)
    # else:
    collection = client.get_or_create_collection(name=collection_name)


    # Load schema from CSV
    schema_structure = load_schema_from_csv(csv_path)
    if not schema_structure:
        print("Failed to load or process schema from CSV. Aborting indexing.")
        return

    documents, metadatas, ids = create_schema_documents_from_structure(schema_structure)
    
    if not documents:
        print("No schema documents generated. Please check your CSV file and processing logic.")
        return

    print(f"Generated {len(documents)} documents for indexing from CSV.")
    
    try:
        # Ensure no duplicate IDs if re-running without clearing effectively
        # Or handle by add/update logic if ChromaDB version supports it easily
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        print(f"Successfully indexed {len(documents)} schema documents into collection '{collection_name}'.")
        print(f"Total documents in collection: {collection.count()}")
    except Exception as e:
        print(f"Error indexing documents: {e}")

def query_schema(query_texts, n_results=10, collection_name=SCHEMA_COLLECTION_NAME):
    """
    Queries the schema collection in ChromaDB.
    """
    try:
        collection_to_query = client.get_collection(name=collection_name) # Use get_collection for querying
        results = collection_to_query.query(
            query_texts=query_texts,
            n_results=n_results,
            include=["metadatas", "documents"]
        )
        return results
    except Exception as e: 
        # This is where your error message is generated
        print(f"Error querying schema in collection '{collection_name}': {e}. Collection might not exist or be empty.")
        return None

if __name__ == "__main__":
    print("Starting schema indexing process from CSV...")
    # Create a dummy database_schema.csv for testing if it doesn't exist
    dummy_csv_path = SCHEMA_CSV_FILE_PATH
    if not os.path.exists(dummy_csv_path):
        print(f"Creating a dummy '{os.path.basename(dummy_csv_path)}' for testing purposes.")
        dummy_data = {
            'mainTableName': ['ALLOCATION_BASE', 'ALLOCATION_BASE', 'ALLOCATION_BASE', 'ALLOCATION_BASE', 'ORDERS', 'ORDERS', 'ORDER_ITEMS', 'ORDER_ITEMS'],
            'COLUMN_NAME': ['ALLOC_SEQ_NO', 'ALLOC_TYPE_QUAL_GID', 'ALLOCATED_COST', 'ALLOCATED_COST_BASE', 'ORDER_ID', 'CUSTOMER_NAME', 'ITEM_ID', 'ORDER_ID'],
            'DATA_TYPE': ['bigint', 'datetime', 'float', 'float', 'varchar', 'varchar', 'int', 'varchar'],
            'referenceTableName': [None, None, None, None, None, None, None, 'ORDERS'],
            'refColumnName': [None, None, None, None, None, None, None, 'ORDER_ID'],
            'TABLE_DESCRIPTION': ['Base table for allocations', 'Base table for allocations', 'Base table for allocations','Base table for allocations', 'Contains customer orders', 'Contains customer orders', 'Line items for orders', 'Line items for orders'],
            'COLUMN_DESCRIPTION':['Sequence number for allocation', 'Allocation type qualifier GID', 'The allocated cost value', 'Base value of allocated cost', 'Unique ID for the order', 'Name of the customer placing the order', 'Unique ID for the item', 'Foreign key to the orders table']
        }
        pd.DataFrame(dummy_data).to_csv(dummy_csv_path, index=False)
        print(f"Dummy CSV created at {dummy_csv_path}")
    
    index_schema(csv_path=dummy_csv_path) # Use the path to your actual CSV
    print("\nSchema indexing process finished.")

    print("\n--- Testing schema query ---")
    # Ensure collection exists and has documents before querying
    try:
        collection_for_test = client.get_collection(name=SCHEMA_COLLECTION_NAME)
        if collection_for_test.count() > 0:
            test_queries = [
                "allocated costs",
                "customer orders information",
                "items in an order"
            ]
            for query_text in test_queries:
                print(f"\nQuerying for: '{query_text}'")
                query_results = query_schema(query_texts=[query_text], n_results=3)
                if query_results and query_results.get('documents') and query_results['documents'][0]:
                    for i, doc in enumerate(query_results['documents'][0]):
                        print(f"  Result {i+1}: {doc}")
                        print(f"    Metadata: {query_results['metadatas'][0][i]}")
                else:
                    print("  No results found or error in querying.")
        else:
            print("Skipping test query as collection is empty.")
    except Exception as e:
        print(f"Skipping test query due to error getting collection: {e}")