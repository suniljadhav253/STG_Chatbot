# app/app.py
import os
from flask import Flask
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(dotenv_path='../.env') # Adjusted path relative to app/app.py

def create_app():
    app = Flask(__name__)

    # Configuration (can also be moved to a config.py file)
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_default_secret_key_for_development')
    app.config['OPENAI_API_KEY'] = os.environ.get('OPENAI_API_KEY')
    # Add other configurations as needed (e.g., database URI)
    app.config['DB_HOST'] = os.environ.get('DATABASE_SERVER')
    # app.config['DB_PORT'] = os.environ.get('DATABASE_PORT')
    app.config['DB_NAME'] = os.environ.get('DATABASE_NAME')
    app.config['DB_USER'] = os.environ.get('DATABASE_USERNAME')
    app.config['DB_PASSWORD'] = os.environ.get('DATABASE_PASSWORD')

    # Example: Construct a Database URI (adjust based on your DB)
    # For SQLAlchemy:
    # app.config['SQLALCHEMY_DATABASE_URI'] = f"postgresql://{app.config['DB_USER']}:{app.config['DB_PASSWORD']}@{app.config['DB_HOST']}:{app.config['DB_PORT']}/{app.config['DB_NAME']}"
    # app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions here (e.g., db for SQLAlchemy, ChromaDB client)

    # Import and register blueprints/routes
    from . import routes
    app.register_blueprint(routes.bp) # Assuming routes are in a Blueprint named 'bp'

    # A simple test route
    @app.route('/hello')
    def hello():
        return 'Hello, Logistics AI!'

    return app

if __name__ == '__main__':
    # This part is for running with `python app/app.py`
    # For production, use a WSGI server like Gunicorn or Waitress
    # Ensure the .env file is loaded if running this script directly
    # and it's located in the project_root, not app/
    # So, if running `python app/app.py`, load_dotenv() at the top of this file
    # should ideally point to '../.env'
    app_instance = create_app()
    app_instance.run(debug=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true',
                     host='0.0.0.0',
                     port=int(os.environ.get('FLASK_PORT', 5000)))