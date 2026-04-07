"""
EduCode Refactoring Game — Flask Backend Entry Point

This is the main application factory that:
  1. Initializes Flask with configuration
  2. Registers blueprints (escape room + open world routes)
  3. Sets up the Gemini API client
  4. Starts the development or production server

Configuration:
  GEMINI_API_KEY      → set in .env or environment
  SESSION_STORE_TTL   → 7200 seconds (2 hours) by default
  DEBUG               → optional (development mode)
  PORT                → 5001 (default)
"""

import os
import google.generativeai as genai
from flask import Flask
from flask_cors import CORS

# Import blueprints
from routes.edumode_routes import edumode_bp
from routes.world_routes import world_bp


def create_app(config_path: str = None) -> Flask:
    """
    Application factory for EduCode backend.
    
    Args:
        config_path: Optional path to a config Python file
    
    Returns:
        Configured Flask application
    """
    app = Flask(__name__)
    
    # ─ Configuration ──────────────────────────────────────────────────────────
    
    # Default configuration
    app.config['JSON_SORT_KEYS'] = False
    app.config['PROPAGATE_EXCEPTIONS'] = True
    
    # Session configuration
    app.config['SESSION_COOKIE_SECURE'] = False      # set True in production
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    # Load from environment or .env file
    if os.path.exists('.env'):
        from dotenv import load_dotenv
        load_dotenv('.env')
    
    # Gemini API key (required)
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if not gemini_api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY not set. "
            "Create a .env file with GEMINI_API_KEY=your_key_here"
        )
    
    app.config['GEMINI_API_KEY'] = gemini_api_key

    # Configure Gemini model once so routes can reuse it.
    model_name = os.getenv('GEMINI_MODEL_NAME', 'gemini-1.5-flash')
    app.config['GEMINI_MODEL_NAME'] = model_name
    try:
        genai.configure(api_key=gemini_api_key)
        app.config['GEMINI_MODEL'] = genai.GenerativeModel(model_name)
    except Exception as exc:
        raise EnvironmentError(f"Failed to initialize Gemini model '{model_name}': {exc}")
    
    # Load custom config if provided
    if config_path:
        app.config.from_pyfile(config_path)
    
    # ─ CORS Setup ─────────────────────────────────────────────────────────────
    # Allow Unity clients from localhost during development
    CORS(app, resources={
        r"/edumode/*": {
            "origins": ["http://localhost:*", "http://127.0.0.1:*"],
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type"]
        },
        r"/world/*": {
            "origins": ["http://localhost:*", "http://127.0.0.1:*"],
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type"]
        }
    })
    
    # ─ Blueprint Registration ─────────────────────────────────────────────────
    
    # Escape Room mode routes
    app.register_blueprint(edumode_bp, url_prefix='/edumode')
    
    # Open World / GitHub mode routes
    app.register_blueprint(world_bp, url_prefix='/world')
    
    # ─ Global Error Handler ───────────────────────────────────────────────────
    
    @app.errorhandler(400)
    def bad_request(e):
        return {"success": False, "error": str(e)}, 400
    
    @app.errorhandler(404)
    def not_found(e):
        return {"success": False, "error": "Endpoint not found"}, 404
    
    @app.errorhandler(500)
    def internal_error(e):
        return {"success": False, "error": "Internal server error"}, 500
    
    return app


if __name__ == '__main__':
    # Development server
    app = create_app()
    
    port = int(os.getenv('PORT', 5001))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    print(f"""
    
    ╔══════════════════════════════════════════════════════════════════════════╗
    ║                  EduCode Refactoring Game Backend                        ║
    ║                       Running on port {port}                              ║
    ║                                                                          ║
    ║  Endpoints:                                                              ║
    ║    POST   /edumode/generate              Create a puzzle                ║
    ║    POST   /edumode/hint                  Request next hint              ║
    ║    POST   /edumode/hint/replay           Replay a hint stage           ║
    ║    POST   /edumode/validate              Validate refactored code      ║
    ║    POST   /world/analyze                 Analyze a codebase            ║
    ║    POST   /world/engage                  Start a world challenge       ║
    ║    POST   /world/advance                 Mark challenge complete       ║
    ║                                                                          ║
    ║  Press CTRL+C to stop the server.                                       ║
    ╚══════════════════════════════════════════════════════════════════════════╝
    """)
    
    app.run(host='0.0.0.0', port=port, debug=debug, threaded=True)
