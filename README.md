
# 🤖 STG Chatbot

**STG Chatbot** is an intelligent, Python-based conversational assistant designed to provide insights or data-driven answers using structured input such as database schemas or text files. This project is ideal for building internal business assistants or data-interaction bots.

---


## 🚀 Features

- 🧠 Natural language interface for querying structured data
- 📊 CSV-based schema and insight processing
- 🗂️ Integration with embeddings or vector database (e.g., via `chroma_data`)
- 💬 Supports query samples and prompt-based learning
- 🛠️ Modular and extensible code structure

---

## 🧰 Prerequisites

Make sure you have the following installed:

- Python 3.8+
- Git
- (Optional) Visual Studio Code or any IDE of your choice

---

## 🔧 Getting Started

Follow these steps to set up and run the project locally:

### 1. Clone the Repository

```bash
git clone https://github.com/suniljadhav253/STG_Chatbot.git
cd STG_Chatbot
````

### 2. Create and Activate a Virtual Environment

#### On Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

#### On macOS/Linux:

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the Application

Depending on your entry point (e.g., `main.py`, `app.py`, or notebook), run:

```bash
python app.py
```

or if it's a notebook:

```bash
jupyter notebook
```

---

## 🧪 Sample Queries

You can find pre-written queries in `sampleQueries.txt` to test the chatbot. These are examples of how to interact using natural language.

---

## 🛡️ Environment Variables (Optional)

If your app uses API keys or secrets (like OpenAI, Pinecone, etc.), create a `.env` file in the root directory:

```env
OPENAI_API_KEY=your-api-key-here
DB_USER=username
DB_PASS=password
```

And make sure `.env` is in `.gitignore`.

---

## 📦 Requirements

All Python dependencies are listed in `requirements.txt`. To update:

```bash
pip install -r requirements.txt
```

---

## 👤 Author

**Sunil Jadhav**
GitHub: [@suniljadhav253](https://github.com/suniljadhav253)
