# app/extensions.py
"""Initialize Flask extensions."""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

# Database ORM
db = SQLAlchemy()

# Database Migrations
migrate = Migrate()

# Login Session Management
login_manager = LoginManager()

# Configure login manager (adjust as needed for API vs HTML responses)
# login_manager.login_view = 'auth.login' # Example if using blueprints later
# login_manager.login_message_category = 'info'
@login_manager.unauthorized_handler
def unauthorized():
    # Return JSON error for API calls when login is required but user isn't authenticated
    # Note: This requires Flask-Login 0.5.0+
    # For older versions, you might need app.errorhandler(401)
    from flask import jsonify # Local import to avoid circular dependency issues at startup
    return jsonify(error="Login required"), 401

# User loader callback is defined in create_app where User model is accessible
# Or it could be defined here if User model is imported carefully
