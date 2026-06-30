"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  models_vehicleimage.py                                                     ║
║  Append the class below to the END of your existing models.py               ║
║  (after your Vehicle class).  No existing code changes needed.              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from datetime import datetime, timedelta, timezone as _tz

_IST = _tz(timedelta(hours=5, minutes=30))

def _now_ist():
    return datetime.now(_IST).replace(tzinfo=None)


class VehicleImage(db.Model):
    """
    Extra gallery images for a vehicle.

    The primary image stays in vehicles.image_filename (unchanged).
    These are additional photos shown in the detail-page gallery carousel.
    Deleting a Vehicle cascades to delete its VehicleImage rows automatically.
    """
    __tablename__ = 'vehicle_images'

    id          = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    vehicle_id  = db.Column(
                    db.Integer,
                    db.ForeignKey('vehicles.id', ondelete='CASCADE'),
                    nullable=False,
                    index=True
                  )
    filename    = db.Column(db.String(255), nullable=False)
    sort_order  = db.Column(db.Integer,     default=0)
    created_at  = db.Column(db.DateTime,    default=_now_ist)

    vehicle = db.relationship(
        'Vehicle',
        backref=db.backref(
            'extra_images_rel',
            lazy='dynamic',
            cascade='all, delete-orphan'
        )
    )

    def __repr__(self):
        return f'<VehicleImage vehicle={self.vehicle_id} file={self.filename}>'
