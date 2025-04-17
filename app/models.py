# app/models.py
"""Database models."""

from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from sqlalchemy.dialects.postgresql import JSONB # Import JSONB if using that approach
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

    # Relationship to FitFile
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
    # Updated status options
    processing_status = db.Column(
        db.String(50),
        default='uploaded', # Default status on creation
        nullable=False,
        index=True
    ) # Options: 'uploaded', 'analysis_pending', 'processing', 'processed', 'analysis_failed'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)

    # Relationship to PowerCurvePoint (one-to-many)
    power_curve_points = db.relationship(
        'PowerCurvePoint',
        backref='fit_file',
        lazy='dynamic', # Use dynamic loading if expecting many points per file
        cascade="all, delete-orphan" # Delete points if FitFile is deleted
    )

    def get_full_path(self) -> str:
        """Helper to get the absolute path to the stored file."""
        base_dir = current_app.config.get('FIT_DIR', 'fitfiles')
        return os.path.join(base_dir, self.storage_path)

    def __repr__(self):
        return f'<FitFile {self.id}: {self.original_filename} User {self.user_id}>'

# New table for storing individual power curve data points
class PowerCurvePoint(db.Model):
    __tablename__ = 'power_curve_point'
    id = db.Column(db.Integer, primary_key=True)
    duration_seconds = db.Column(db.Integer, nullable=False, index=True)
    max_power_watts = db.Column(db.Float, nullable=False)
    # Foreign key linking back to the FitFile
    fit_file_id = db.Column(
        db.Integer,
        db.ForeignKey('fit_file.id', ondelete='CASCADE'), # Link to fit_file table, cascade deletes
        nullable=False,
        index=True
    )

    # Optional: Add a unique constraint if needed (e.g., only one point per duration per file)
    # __table_args__ = (db.UniqueConstraint('fit_file_id', 'duration_seconds', name='_fit_file_duration_uc'),)

    def __repr__(self):
        return f'<PowerCurvePoint File:{self.fit_file_id} Duration:{self.duration_seconds} Power:{self.max_power_watts}>'

