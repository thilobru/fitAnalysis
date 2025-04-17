# app/files/routes.py
"""Blueprint for file management API routes."""

import os
import uuid
import logging
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from typing import Tuple

# Import db instance and models
from ..extensions import db
from ..models import FitFile, User

# Import helper functions and NEW calculation function
from ..services import _allowed_file, _extract_activity_date, calculate_and_save_single_file_power_curve

logger = logging.getLogger(__name__)
# Create Blueprint instance with URL prefix
bp = Blueprint('files', __name__, url_prefix='/api')

@bp.route('/files', methods=['POST'])
@login_required
def upload_file() -> Tuple[str, int]:
    """Handles FIT file uploads and triggers synchronous analysis."""
    if 'file' not in request.files:
        logger.warning(f"File upload attempt failed for user {current_user.id}: No file part.")
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files['file']
    if not file or not file.filename:
        logger.warning(f"File upload attempt failed for user {current_user.id}: No selected file.")
        return jsonify({"error": "No selected file"}), 400

    if _allowed_file(file.filename):
        original_filename = secure_filename(file.filename)
        file_ext = os.path.splitext(original_filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        user_id_str = str(current_user.id)
        relative_storage_path = os.path.join(user_id_str, unique_filename)
        full_save_path = os.path.join(current_app.config['FIT_DIR'], relative_storage_path)
        new_fit_file = None # Initialize to None

        try:
            user_dir = os.path.dirname(full_save_path)
            os.makedirs(user_dir, exist_ok=True)
            file.save(full_save_path)
            logger.info(f"File '{original_filename}' uploaded by user {current_user.id} saved to '{full_save_path}'")

            filesize = os.path.getsize(full_save_path)
            activity_date = _extract_activity_date(full_save_path)

            # Create initial record with 'analysis_pending' status
            new_fit_file = FitFile(
                original_filename=original_filename,
                storage_path=relative_storage_path,
                user_id=current_user.id,
                filesize=filesize,
                activity_date=activity_date,
                processing_status='analysis_pending' # Start as pending
            )
            db.session.add(new_fit_file)
            db.session.commit() # Commit to get the ID
            logger.info(f"Database record created for file ID {new_fit_file.id}, status pending.")

            # --- Trigger synchronous analysis ---
            analysis_success = calculate_and_save_single_file_power_curve(new_fit_file.id)
            # ---

            # Re-fetch the file to get the final status after analysis
            db.session.refresh(new_fit_file)

            if analysis_success:
                logger.info(f"Synchronous analysis completed successfully for file ID {new_fit_file.id}")
                return jsonify({
                    "message": "File uploaded and processed successfully",
                    "file": {
                        "id": new_fit_file.id,
                        "filename": new_fit_file.original_filename,
                        "date": new_fit_file.activity_date.strftime('%Y-%m-%d') if new_fit_file.activity_date else None,
                        "status": new_fit_file.processing_status # Should be 'processed'
                    }
                }), 201
            else:
                logger.error(f"Synchronous analysis failed for file ID {new_fit_file.id}")
                # Return success for upload, but indicate analysis failure
                return jsonify({
                    "message": "File uploaded, but analysis failed. Check server logs.",
                    "file": {
                        "id": new_fit_file.id,
                        "filename": new_fit_file.original_filename,
                        "date": new_fit_file.activity_date.strftime('%Y-%m-%d') if new_fit_file.activity_date else None,
                        "status": new_fit_file.processing_status # Should be 'analysis_failed'
                    }
                }), 207 # Multi-Status (Upload OK, Analysis Failed)

        except Exception as e:
            db.session.rollback() # Rollback DB changes
            logger.error(f"Error during file upload or analysis trigger for user {current_user.id}, file '{original_filename}': {e}", exc_info=True)
            # Clean up saved file if it exists and DB record wasn't fully processed
            if os.path.exists(full_save_path):
                 try:
                     os.remove(full_save_path)
                     logger.info(f"Cleaned up failed upload file: {full_save_path}")
                 except OSError:
                     logger.error(f"Could not clean up failed upload file: {full_save_path}")
            # If analysis failed after initial commit, the record might still exist, update status
            if new_fit_file and new_fit_file.id:
                 try:
                     # Use a new session or merge if necessary after rollback, or just update status if possible
                     # For simplicity, we might just log the error and return 500
                     logger.error(f"File record {new_fit_file.id} might remain in pending state after error.")
                 except Exception as db_err:
                      logger.error(f"Further error trying to handle DB state after upload error: {db_err}")

            return jsonify({"error": "Failed to save file or trigger analysis"}), 500
    else:
        logger.warning(f"File upload attempt failed for user {current_user.id}: File type '{file.filename}' not allowed.")
        allowed_ext_str = ", ".join(current_app.config.get('ALLOWED_EXTENSIONS', {'.fit'}))
        return jsonify({"error": f"File type not allowed. Allowed: {allowed_ext_str}"}), 400


@bp.route('/files', methods=['GET'])
@login_required
def get_user_files() -> Tuple[str, int] | str :
    """API endpoint to get the list of FIT files for the logged-in user."""
    user_id = getattr(current_user, 'id', None)
    logger.info(f"Request received for /api/files list for user {user_id}")
    try:
        # Order by upload time descending
        files_query = current_user.fit_files.order_by(FitFile.upload_timestamp.desc())
        files = files_query.all()

        details = [{
            "id": f.id,
            "filename": f.original_filename,
            "date": f.activity_date.strftime('%Y-%m-%d') if f.activity_date else None,
            "uploaded": f.upload_timestamp.isoformat(),
            "size_kb": round(f.filesize / 1024) if f.filesize else None,
            "status": f.processing_status # Show current status
        } for f in files]

        return jsonify(details), 200
    except Exception as e:
        logger.error(f"Error fetching files for user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve file list"}), 500


@bp.route('/files/<int:file_id>', methods=['DELETE'])
@login_required
def delete_file(file_id: int) -> Tuple[str, int]:
    """Deletes a specific FIT file and its associated power curve points."""
    user_id = getattr(current_user, 'id', None)
    logger.info(f"Request received to delete file {file_id} for user {user_id}")
    try:
        # Find the file ensuring it belongs to the current user
        # The cascade delete on the relationship FitFile.power_curve_points
        # should handle deleting PowerCurvePoint records automatically when
        # the FitFile record is deleted by db.session.delete(fit_file).
        fit_file = current_user.fit_files.filter_by(id=file_id).first()

        if fit_file is None:
            logger.warning(f"Delete request failed: File ID {file_id} not found or not owned by user {user_id}.")
            return jsonify({"error": "File not found"}), 404

        full_path = fit_file.get_full_path()
        storage_path_log = fit_file.storage_path

        # Try to delete file from filesystem first
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
                logger.info(f"Deleted file from filesystem: {full_path}")
            except OSError as e:
                logger.error(f"Error deleting file {full_path} from filesystem: {e}. Proceeding to delete DB record.")
        else:
            logger.warning(f"File not found on filesystem for deletion: {full_path} (DB record for {storage_path_log} will be deleted).")

        # Proceed to delete DB record (cascade should delete PowerCurvePoints)
        db.session.delete(fit_file)
        db.session.commit()
        logger.info(f"Successfully deleted file record ID {file_id} and associated data for user {user_id}.")
        return jsonify({"message": "File deleted successfully"}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting file ID {file_id} for user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to delete file"}), 500
