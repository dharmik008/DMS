"""
utils/cds_helper.py  —  Centralized Document Storage helper
============================================================
Provides a single `register_upload()` function any module can call
immediately after saving a file to disk, to register it in the
master Central Document Storage.

Usage example (in any route):
    from utils.cds_helper import register_upload

    filename = save_my_file(...)
    register_upload(
        file_name     = filename,
        file_path     = os.path.join('images', 'uploads', filename),
        module_name   = 'Invoices',       # or 'Deals', 'Reports', 'CRM', …
        document_type = 'Sale Invoice',
        dealer_id     = dealer_id,
        uploaded_by   = dealer_id,
        original_name = original_filename,
        performed_by  = f'dealer:{dealer_id}',
    )

The function is wrapped in try/except so it NEVER breaks the caller's
upload flow even if the CDS registration fails for any reason.
"""

import os


def register_upload(
    file_name: str,
    file_path: str,
    module_name: str,
    document_type: str = '',
    dealer_id: int = None,
    uploaded_by: int = None,
    original_name: str = None,
    performed_by: str = 'system',
) -> bool:
    """
    Register a newly saved file into the Central Document Storage.

    Parameters
    ----------
    file_name     : stored filename on disk (e.g. 'abc123.pdf')
    file_path     : relative path from the app's static/ folder
                    (e.g. 'images/uploads/abc123.pdf')
    module_name   : human label of the source module
                    ('Documents', 'KYC', 'Vehicles', 'Deals',
                     'Invoices', 'Reports', 'CRM', …)
    document_type : sub-type label (e.g. 'RC Book', 'Sale Invoice')
    dealer_id     : owning dealer's user id (or None for admin-only files)
    uploaded_by   : user id who triggered the upload
    original_name : browser-provided original filename
    performed_by  : string for audit log ('dealer:3', 'admin', …)

    Returns True on success, False if registration silently failed.
    """
    try:
        from db import cds_register
        cds_register({
            'dealer_id':     dealer_id,
            'file_name':     file_name,
            'original_name': original_name or file_name,
            'file_path':     file_path,
            'module_name':   module_name,
            'document_type': document_type,
            'uploaded_by':   uploaded_by,
            'performed_by':  performed_by,
        })
        return True
    except Exception:
        # Never break the calling route
        return False


def register_kyc_upload(dealer_id: int, filename: str, doc_key: str,
                        subfolder_path: str = None) -> bool:
    """Convenience wrapper specifically for KYC documents."""
    path = subfolder_path or os.path.join('uploads', 'dealers', str(dealer_id), filename)
    return register_upload(
        file_name     = filename,
        file_path     = path,
        module_name   = 'KYC',
        document_type = doc_key.replace('_', ' ').title(),
        dealer_id     = dealer_id,
        uploaded_by   = dealer_id,
        performed_by  = f'dealer:{dealer_id}',
    )


def register_vehicle_upload(dealer_id: int, filename: str,
                            image_type: str = 'gallery') -> bool:
    """Convenience wrapper for vehicle image uploads."""
    return register_upload(
        file_name     = filename,
        file_path     = os.path.join('images', 'uploads', filename),
        module_name   = 'Vehicles',
        document_type = image_type.replace('_', ' ').title(),
        dealer_id     = dealer_id,
        uploaded_by   = dealer_id,
        performed_by  = f'dealer:{dealer_id}',
    )
