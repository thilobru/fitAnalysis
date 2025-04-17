# app/models.py
"""Database models."""

from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from .extensions import db # Import db instance from extensions.py
from flask import current_app # Use current_app to access config safely
import os

# Add UserMixin for Flask-Login integration
class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    fit_files = db.relationship('FitFile', backref='owner', lazy='dynamic', cascade="all, delete-orphan")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class FitFile(db.Model):
    __tablename__ = 'fit_file'
    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(255), nullable=False)
    storage_path = db.Column(db.String(512), nullable=False, unique=True) # Relative path: <user_id>/<uuid>.fit
    upload_timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    activity_date = db.Column(db.Date, nullable=True)
    filesize = db.Column(db.Integer, nullable=True) # In bytes
    processing_status = db.Column(db.String(50), default='uploaded')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)

    def get_full_path(self) -> str:
        """Helper to get the absolute path to the stored file."""
        # Use current_app.config within application context
        base_dir = current_app.config.get('FIT_DIR', 'fitfiles') # Use default if not set
        return os.path.join(base_dir, self.storage_path)

    def __repr__(self):
        return f'<FitFile {self.original_filename} User {self.user_id}>'

