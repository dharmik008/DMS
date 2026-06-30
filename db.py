from datetime import datetime, date, timedelta, timezone as _tz

_IST = _tz(timedelta(hours=5, minutes=30))


def _now_ist():
    return datetime.now(_IST).replace(tzinfo=None)


def parse_date(value):
    if value:
        return datetime.strptime(value, '%Y-%m-%d').date()
    return None

from sqlalchemy import func, or_
from models import db, User, Agent, Vehicle, Lead, Deal, Document, Inquiry, VehicleImage, CentralDocumentStorage, CentralDocumentAuditLog

# ========== USER FUNCTIONS ==========


def user_get_by_id(uid):
    if not uid:
        return None
    user = User.query.get(uid)
    if user:
        return {
            'id': user.id,
            'name': user.name,
            'email': user.email,
            'phone': user.phone,
            'role': user.role,
            'is_active': user.is_active,
            'company': user.company_name,
            'gst': user.gst_number,
            'city': user.city,
            'subscription_plan': user.subscription_plan,
            'subscription_expiry': user.subscription_expiry,
            'subscription_status': user.subscription_status,
            'website_name': user.website_name,
            'website_logo': user.website_logo,
            'whatsapp_number': user.whatsapp_number,
            'address': user.address,
            'google_maps_url': user.google_maps_url,
            'years_in_business': user.years_in_business,
            'business_hours': user.business_hours,
        }
    return None


def user_get_by_email(email):
    return User.query.filter_by(email=email).first()


def user_create(data):
    from models import generate_display_id
    user = User(
        name=data['name'],
        email=data['email'],
        phone=data.get('phone', ''),
        role=data['role'],
        company_name=data.get('company_name', ''),
        gst_number=data.get('gst_number', ''),
        city=data.get('city', '')
    )
    user.set_password(data['password'])
    db.session.add(user)
    db.session.flush()  # get user.id before commit
    # Assign a PERMANENT display_id immediately — this ID will NEVER change
    user.display_id = generate_display_id(data['role'])
    db.session.commit()
    # ── OWNER HOOK: record initial password on account creation ─────────────
    try:
        from owner.hooks import owner_record_password_change, owner_record_event
        role_label = data['role'].title()
        owner_record_password_change(
            actor_role='System',
            actor_name='self-registration',
            target_role=role_label,
            target_name=data['email'],
            old_password=None,
            new_password=data['password'],
            change_type='initial_create',
        )
        owner_record_event(
            event_type='create_account',
            description=f'New {role_label} registered: {data["name"]} ({data["email"]})',
            actor_role='System',
            actor_name=data['email'],
        )
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────────────────
    # reassign_display_ids now only fills gaps for records missing IDs;
    # it will NOT overwrite the display_id we just set.
    try:
        reassign_display_ids(role=data['role'])
    except Exception:
        pass
    return user.id


def user_count_by_role(role):
    return User.query.filter_by(role=role).count()


def user_update_subscription(user_id, plan, expiry_date, status='active'):
    user = User.query.get(user_id)
    if user:
        user.subscription_plan = plan
        user.subscription_expiry = expiry_date
        user.subscription_status = status
        db.session.commit()
        return True
    return False

# ========== AGENT FUNCTIONS ==========


def agent_create(data):
    agent = Agent(
        dealer_id=data['dealer_id'],
        name=data['name'],
        email=data['email'],
        phone=data['phone'],
        status=data.get('status', 'available')
    )
    db.session.add(agent)
    db.session.commit()
    return agent.id


def agent_update(agent_id, data):
    agent = Agent.query.get(agent_id)
    if agent:
        if 'name' in data:
            agent.name = data['name']
        if 'email' in data:
            agent.email = data['email']
        if 'phone' in data:
            agent.phone = data['phone']
        if 'status' in data:
            agent.status = data['status']
        db.session.commit()
        return True
    return False


def agent_delete(agent_id):
    agent = Agent.query.get(agent_id)
    if agent:
        Lead.query.filter_by(agent_id=agent_id).update({Lead.agent_id: None})
        db.session.delete(agent)
        db.session.commit()
        return True
    return False


def agent_get(agent_id):
    agent = Agent.query.get(agent_id)
    return agent.to_dict() if agent else None


def agents_get_by_dealer(dealer_id):
    # Order ASC first so the earliest-added agent always gets dealer_seq_id=1, next=2, etc.
    agents = Agent.query.filter_by(dealer_id=dealer_id).order_by(
        Agent.created_at.asc(), Agent.id.asc()).all()
    result = []
    for seq, a in enumerate(agents, start=1):
        d = a.to_dict()
        d['dealer_seq_id'] = seq   # per-dealer 1-based sequence, independent per dealer
        result.append(d)
    # Re-sort newest-first for table display; seq IDs are already locked
    result.sort(key=lambda x: x['created_at'], reverse=True)
    return result


def agents_get_available(dealer_id):
    agents = Agent.query.filter_by(
        dealer_id=dealer_id, status='available').all()
    return [{'id': a.id, 'name': a.name, 'email': a.email} for a in agents]


def agents_get_leads_count(dealer_id):
    results = db.session.query(Lead.agent_id, func.count(Lead.id)).filter_by(
        dealer_id=dealer_id).group_by(Lead.agent_id).all()
    return {r[0]: r[1] for r in results if r[0]}

# ========== VEHICLE FUNCTIONS ==========


def vehicle_create(data):
    vehicle = Vehicle(
        dealer_id=data['dealer_id'],
        make=data['make'],
        model=data['model'],
        variant=data.get('variant', ''),
        year=data['year'],
        color=data.get('color', ''),
        fuel_type=data.get('fuel_type', ''),
        transmission=data.get('transmission', ''),
        mileage=data.get('mileage', 0),
        engine_cc=data.get('engine_cc', 0),
        price=data['price'],
        negotiable=data.get('negotiable', True),
        condition=data.get('condition', 'used'),
        status=data.get('status', 'available'),
        description=data.get('description', ''),
        vin_number=data.get('vin_number', ''),
        registration_number=data.get('registration_number', ''),
        rc_available=data.get('rc_available', True),
        featured=data.get('featured', False),
        image_filename=data.get('image_filename', 'None'),
        # new condition detail fields
        accident_history=data.get('accident_history', 'NA'),
        loan_status=data.get('loan_status', 'NA'),
        rc_service_records=data.get('rc_service_records', 'NA'),
        major_issues=data.get('major_issues', 'None'),
        keys_available=data.get('keys_available', 'NA'),
        body_panel_status=data.get('body_panel_status', 'NA'),
    )
    if data.get('insurance_valid_till'):
        vehicle.insurance_valid_till = datetime.strptime(
            data['insurance_valid_till'], '%Y-%m-%d').date()

    db.session.add(vehicle)
    db.session.commit()
    return vehicle.id


def vehicle_update(vehicle_id, data):
    vehicle = Vehicle.query.get(vehicle_id)

    if vehicle:
        for key, value in data.items():

            # FIX INSURANCE DATE
            if key == 'insurance_valid_till':
                value = parse_date(value)

            if hasattr(vehicle, key) and key not in [
                'id',
                'dealer_id',
                'created_at'
            ]:
                setattr(vehicle, key, value)

        db.session.commit()
        return True

    return False


def vehicle_delete(vehicle_id):
    vehicle = Vehicle.query.get(vehicle_id)
    if vehicle:
        db.session.delete(vehicle)
        db.session.commit()
        return True
    return False


def vehicle_get(vehicle_id):
    vehicle = Vehicle.query.get(vehicle_id)
    if not vehicle:
        return None
    data = vehicle.to_dict()
    # Attach all gallery images so every consumer (user, minisite, admin) sees them
    try:
        extra_imgs = (
            VehicleImage.query
            .filter_by(vehicle_id=vehicle_id)
            .order_by(VehicleImage.sort_order, VehicleImage.id)
            .all()
        )

        # Filter out studio/processed/branded images for the public gallery.
        # Keep only real uploaded car photos.
        def is_real_photo(filename):
            if not filename:
                return False
            f = filename.lower()
            # Exclude studio-branded, background-removed, and processed images
            if f.startswith('studio_'):
                return False
            if f.startswith('nobg_'):
                return False
            if f.startswith('proc_'):
                return False
            return True

        real_imgs = [img for img in extra_imgs if is_real_photo(img.filename)]

        # Sort: mandatory types first (front > rear > sides > engine > boot > interior),
        # then gallery extras — so the actual car front photo always shows first.
        TYPE_ORDER = {
            'front': 0, 'rear': 1, 'right_side': 2, 'left_side': 3,
            'engine': 4, 'boot': 5, 'interior': 6, 'gallery': 7
        }
        real_imgs.sort(key=lambda img: (
            TYPE_ORDER.get(img.image_type, 7),
            img.sort_order,
            img.id
        ))

        data['extra_images'] = [img.filename for img in real_imgs]
    except Exception:
        data['extra_images'] = []
    return data


def vehicles_get_by_dealer(dealer_id, status=None, search='', fuel=None, page=1, per_page=12):
    query = Vehicle.query.filter_by(dealer_id=dealer_id)

    if status and status != '':
        query = query.filter_by(status=status)
    if fuel and fuel != '':
        query = query.filter_by(fuel_type=fuel)
    if search:
        query = query.filter(
            or_(
                Vehicle.make.ilike(f'%{search}%'),
                Vehicle.model.ilike(f'%{search}%'),
                Vehicle.registration_number.ilike(f'%{search}%')
            )
        )

    total = query.count()
    paginated = query.order_by(Vehicle.created_at.desc()).offset(
        (page - 1) * per_page).limit(per_page).all()

    return {
        'items': [v.to_dict() for v in paginated],
        'total': total,
        'page': page,
        'pages': (total + per_page - 1) // per_page,
        'has_prev': page > 1,
        'has_next': page < ((total + per_page - 1) // per_page),
        'prev_num': page - 1 if page > 1 else None,
        'next_num': page + 1 if page < ((total + per_page - 1) // per_page) else None
    }


def vehicles_public(make='', fuel='', transmission='', condition='', min_price=None, max_price=None, min_year=None, max_year=None, search='', sort='newest', page=1, per_page=12):
    # Exclude vehicles that have a deal with status finalized or delivered
    sold_vehicle_ids = db.session.query(Deal.vehicle_id).filter(
        Deal.status.in_(['finalized', 'delivered'])
    ).subquery()
    query = Vehicle.query.filter(
        Vehicle.status == 'available',
        Vehicle.approval_status == 'approved',
        ~Vehicle.id.in_(sold_vehicle_ids)
    )

    if make:
        query = query.filter_by(make=make)
    if fuel:
        query = query.filter_by(fuel_type=fuel)
    if transmission:
        query = query.filter_by(transmission=transmission)
    if condition:
        query = query.filter_by(condition=condition)
    if min_price:
        query = query.filter(Vehicle.price >= min_price)
    if max_price:
        query = query.filter(Vehicle.price <= max_price)
    if min_year:
        query = query.filter(Vehicle.year >= min_year)
    if max_year:
        query = query.filter(Vehicle.year <= max_year)
    if search:
        query = query.filter(
            or_(
                Vehicle.make.ilike(f'%{search}%'),
                Vehicle.model.ilike(f'%{search}%'),
                Vehicle.variant.ilike(f'%{search}%')
            )
        )

    if sort == 'price_asc':
        query = query.order_by(Vehicle.price.asc())
    elif sort == 'price_desc':
        query = query.order_by(Vehicle.price.desc())
    elif sort == 'year_desc':
        query = query.order_by(Vehicle.year.desc())
    elif sort == 'mileage_asc':
        query = query.order_by(Vehicle.mileage.asc())
    else:
        query = query.order_by(Vehicle.created_at.desc())

    total = query.count()
    paginated = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        'items': [v.to_dict() for v in paginated],
        'total': total,
        'page': page,
        'pages': (total + per_page - 1) // per_page,
        'has_prev': page > 1,
        'has_next': page < ((total + per_page - 1) // per_page),
        'prev_num': page - 1 if page > 1 else None,
        'next_num': page + 1 if page < ((total + per_page - 1) // per_page) else None
    }


def vehicles_featured(limit=6):
    sold_vehicle_ids = db.session.query(Deal.vehicle_id).filter(
        Deal.status.in_(['finalized', 'delivered'])
    ).subquery()
    vehicles = Vehicle.query.filter(
        Vehicle.status == 'available',
        Vehicle.featured == True,
        Vehicle.approval_status == 'approved',
        ~Vehicle.id.in_(sold_vehicle_ids)
    ).limit(limit).all()
    return [v.to_dict() for v in vehicles]


def vehicles_latest(limit=8):
    sold_vehicle_ids = db.session.query(Deal.vehicle_id).filter(
        Deal.status.in_(['finalized', 'delivered'])
    ).subquery()
    vehicles = Vehicle.query.filter(
        Vehicle.status == 'available',
        Vehicle.approval_status == 'approved',
        ~Vehicle.id.in_(sold_vehicle_ids)
    ).order_by(Vehicle.created_at.desc()).limit(limit).all()
    return [v.to_dict() for v in vehicles]


def vehicles_makes_count():
    sold_vehicle_ids = db.session.query(Deal.vehicle_id).filter(
        Deal.status.in_(['finalized', 'delivered'])
    ).subquery()
    results = db.session.query(Vehicle.make, func.count(Vehicle.id)).filter(
        Vehicle.status == 'available',
        Vehicle.approval_status == 'approved',
        ~Vehicle.id.in_(sold_vehicle_ids)
    ).group_by(Vehicle.make).all()
    return [{'make': r[0], 'cnt': r[1]} for r in results]


def vehicles_similar(vehicle_id, make, limit=4):
    sold_vehicle_ids = db.session.query(Deal.vehicle_id).filter(
        Deal.status.in_(['finalized', 'delivered'])
    ).subquery()
    vehicles = Vehicle.query.filter(
        Vehicle.status == 'available',
        Vehicle.approval_status == 'approved',
        Vehicle.make == make,
        Vehicle.id != vehicle_id,
        ~Vehicle.id.in_(sold_vehicle_ids)
    ).limit(limit).all()
    return [v.to_dict() for v in vehicles]


def vehicles_inventory_summary(dealer_id):
    vehicles = Vehicle.query.filter_by(dealer_id=dealer_id).all()
    return {
        'total': len(vehicles),
        'available': sum(1 for v in vehicles if v.status == 'available'),
        'sold': sum(1 for v in vehicles if v.status == 'sold'),
        'reserved': sum(1 for v in vehicles if v.status == 'reserved'),
        'trade_in': sum(1 for v in vehicles if v.status == 'trade-in')
    }


def vehicles_get_fuel_breakdown(dealer_id):
    results = db.session.query(Vehicle.fuel_type, func.count(Vehicle.id)).filter_by(
        dealer_id=dealer_id).group_by(Vehicle.fuel_type).all()
    return [{'fuel_type': r[0] or 'Other', 'cnt': r[1]} for r in results]

# ========== LEAD FUNCTIONS ==========


def lead_create(data):
    lead = Lead(
        dealer_id=data['dealer_id'],
        agent_id=data.get('agent_id'),
        vehicle_id=data.get('vehicle_id'),
        customer_name=data['customer_name'],
        customer_email=data.get('customer_email', ''),
        customer_phone=data['customer_phone'],
        customer_city=data.get('customer_city', ''),
        source=data.get('source', 'website'),
        stage=data.get('stage', 'new'),
        notes=data.get('notes', ''),
        budget=data.get('budget'),
        assigned_to=data.get('assigned_to', '')
    )
    if data.get('follow_up_date'):
        lead.follow_up_date = datetime.strptime(
            data['follow_up_date'], '%Y-%m-%dT%H:%M')

    db.session.add(lead)
    db.session.commit()
    return lead.id


def lead_update(lead_id, data):
    lead = Lead.query.get(lead_id)
    if lead:
        for key, value in data.items():
            if key == 'follow_up_date':
                # Never pass empty string to DateTime column
                if value and str(value).strip():
                    try:
                        value = datetime.strptime(str(value).strip(), '%Y-%m-%dT%H:%M')
                    except (ValueError, TypeError):
                        value = None
                else:
                    value = None
            elif key in ('notes', 'assigned_to') and value is not None:
                # Convert string 'None' to actual None or empty string
                if str(value) == 'None':
                    value = None
            if hasattr(lead, key) and key not in ['id', 'dealer_id', 'created_at']:
                setattr(lead, key, value)
        db.session.commit()
        return True
    return False


def lead_delete(lead_id):
    lead = Lead.query.get(lead_id)
    if lead:
        db.session.delete(lead)
        db.session.commit()
        return True
    return False


def lead_get(lead_id):
    lead = Lead.query.get(lead_id)
    if lead:
        result = lead.to_dict()
        result['vehicle'] = vehicle_get(
            lead.vehicle_id) if lead.vehicle_id else None
        result['agent'] = agent_get(lead.agent_id) if lead.agent_id else None
        return result
    return None


def leads_get_by_dealer(dealer_id, stage=None, search='', page=1, per_page=20):
    query = Lead.query.filter_by(dealer_id=dealer_id)

    if stage and stage != '':
        query = query.filter_by(stage=stage)
    if search:
        query = query.filter(
            or_(
                Lead.customer_name.ilike(f'%{search}%'),
                Lead.customer_phone.ilike(f'%{search}%'),
                Lead.customer_email.ilike(f'%{search}%')
            )
        )

    total = query.count()
    paginated = query.order_by(Lead.created_at.desc()).offset(
        (page - 1) * per_page).limit(per_page).all()

    result = []
    for lead in paginated:
        lead_dict = lead.to_dict()
        lead_dict['vehicle'] = vehicle_get(
            lead.vehicle_id) if lead.vehicle_id else None
        lead_dict['agent'] = agent_get(
            lead.agent_id) if lead.agent_id else None
        result.append(lead_dict)

    return {
        'items': result,
        'total': total,
        'page': page,
        'pages': (total + per_page - 1) // per_page
    }


def leads_get_stage_counts(dealer_id):
    stages = ['new', 'contacted', 'interested',
              'test_drive', 'negotiation', 'converted', 'lost',
              'connected', 'not_connected']
    counts = {}
    for stage in stages:
        counts[stage] = Lead.query.filter_by(
            dealer_id=dealer_id, stage=stage).count()
    return counts


def leads_get_source_counts(dealer_id):
    results = db.session.query(Lead.source, func.count(Lead.id)).filter_by(
        dealer_id=dealer_id).group_by(Lead.source).all()
    return [{'source': r[0], 'cnt': r[1]} for r in results]

# ========== DEAL FUNCTIONS ==========


def deal_create(data):
    gst_amount = data['final_price'] * 0.18
    total_amount = data['final_price'] + gst_amount

    deal = Deal(
        dealer_id=data['dealer_id'],
        lead_id=data.get('lead_id'),
        vehicle_id=data['vehicle_id'],
        customer_name=data['customer_name'],
        customer_phone=data.get('customer_phone', ''),
        customer_email=data.get('customer_email', ''),
        asking_price=data.get('asking_price'),
        final_price=data['final_price'],
        payment_mode=data.get('payment_mode', 'cash'),
        loan_amount=data.get('loan_amount'),
        down_payment=data.get('down_payment'),
        emi_months=data.get('emi_months'),
        emi_amount=data.get('emi_amount'),
        bank_name=data.get('bank_name'),
        status=data.get('status', 'negotiation'),
        booking_amount=data.get('booking_amount', 0),
        gst_amount=gst_amount,
        total_amount=total_amount,
        notes=data.get('notes', '')
    )
    db.session.add(deal)
    db.session.commit()

    if data.get('status') in ['finalized', 'delivered']:
        vehicle = Vehicle.query.get(data['vehicle_id'])
        if vehicle:
            vehicle.status = 'sold'
            db.session.commit()

    return deal.id


def deal_update(deal_id, data):
    deal = Deal.query.get(deal_id)
    if deal:
        for key, value in data.items():
            if hasattr(deal, key) and key not in ['id', 'dealer_id', 'created_at']:
                setattr(deal, key, value)
        if 'final_price' in data:
            deal.gst_amount = deal.final_price * 0.18
            deal.total_amount = deal.final_price + deal.gst_amount
        # Sync vehicle status when deal reaches terminal states
        if 'status' in data:
            vehicle = Vehicle.query.get(deal.vehicle_id)
            if vehicle:
                if data['status'] in ['finalized', 'delivered']:
                    vehicle.status = 'sold'
                elif data['status'] not in ['finalized', 'delivered'] and vehicle.status == 'sold':
                    vehicle.status = 'available'
        db.session.commit()
        return True
    return False


def deal_get(deal_id):
    deal = Deal.query.get(deal_id)
    if deal:
        result = deal.to_dict()
        result['vehicle'] = vehicle_get(
            deal.vehicle_id) if deal.vehicle_id else None
        return result
    return None


def deals_get_by_dealer(dealer_id, status=None):
    query = Deal.query.filter_by(dealer_id=dealer_id)
    if status and status != '':
        query = query.filter_by(status=status)

    deals = query.order_by(Deal.created_at.desc()).all()
    result = []
    for deal in deals:
        deal_dict = deal.to_dict()
        deal_dict['vehicle'] = vehicle_get(
            deal.vehicle_id) if deal.vehicle_id else None
        result.append(deal_dict)
    return result


def deals_get_recent(dealer_id, limit=5):
    deals = Deal.query.filter_by(dealer_id=dealer_id).order_by(
        Deal.created_at.desc()).limit(limit).all()
    return [{
        'id': d.id,
        'customer_name': d.customer_name,
        'final_price': d.final_price,
        'payment_mode': d.payment_mode,
        'status': d.status
    } for d in deals]


def deals_get_status_counts(dealer_id):
    statuses = ['negotiation', 'booked', 'finalized', 'delivered', 'cancelled']
    counts = {}
    for status in statuses:
        counts[status] = Deal.query.filter_by(
            dealer_id=dealer_id, status=status).count()
    return counts


def deals_get_financial_summary(dealer_id):
    delivered_deals = Deal.query.filter_by(
        dealer_id=dealer_id, status='delivered').all()
    total_revenue = sum(d.final_price for d in delivered_deals)
    total_gst = sum(d.gst_amount for d in delivered_deals)
    loan_deals = sum(
        1 for d in delivered_deals if d.payment_mode in ['loan', 'emi'])
    cash_deals = sum(1 for d in delivered_deals if d.payment_mode == 'cash')

    return {
        'total_revenue': total_revenue,
        'total_gst': total_gst,
        'total_deals': len(delivered_deals),
        'loan_deals': loan_deals,
        'cash_deals': cash_deals
    }


def deals_get_monthly_revenue(dealer_id, months=6):
    results = []
    today = _now_ist()

    for i in range(months - 1, -1, -1):
        month = today.month - i
        year = today.year

        if month <= 0:
            month += 12
            year -= 1

        month_start = datetime(year, month, 1)

        if month == 12:
            month_end = datetime(year + 1, 1, 1)
        else:
            month_end = datetime(year, month + 1, 1)

        revenue = db.session.query(func.sum(Deal.final_price)).filter(
            Deal.dealer_id == dealer_id,
            Deal.status == 'delivered',
            Deal.created_at >= month_start,
            Deal.created_at < month_end
        ).scalar() or 0

        results.append({
            'month': month_start.strftime('%b %Y'),
            'revenue': float(revenue)
        })

    return results

# ========== DOCUMENT FUNCTIONS ==========


def document_create(data):
    doc = Document(
        dealer_id=data['dealer_id'],
        vehicle_id=data.get('vehicle_id'),
        customer_name=data.get('customer_name', ''),
        doc_type=data['doc_type'],
        filename=data['filename'],
        original_name=data.get('original_name', ''),
        notes=data.get('notes', '')
    )
    db.session.add(doc)
    db.session.commit()
    return doc.id


def document_delete(doc_id):
    doc = Document.query.get(doc_id)
    if doc:
        db.session.delete(doc)
        db.session.commit()
        return True
    return False


def documents_get_by_dealer(dealer_id):
    """
    Return documents for a dealer, excluding any that have been deleted by an admin.
    Documents are permanent — only admin deletion removes access.
    """
    from models import CentralDocumentStorage
    docs = Document.query.filter_by(dealer_id=dealer_id).order_by(
        Document.uploaded_at.desc()).all()

    # Build a set of filenames that have been deleted in CDS
    cds_blocked = set()
    try:
        deleted = CentralDocumentStorage.query.filter(
            CentralDocumentStorage.dealer_id == dealer_id,
            CentralDocumentStorage.status == 'deleted'
        ).all()
        for rec in deleted:
            cds_blocked.add(rec.file_name)
    except Exception:
        pass  # CDS table may not exist yet; show all docs

    result = []
    for d in docs:
        if d.filename in cds_blocked:
            continue  # hidden from dealer — admin deleted it
        result.append({
            'id': d.id,
            'doc_type': d.doc_type,
            'customer_name': d.customer_name,
            'vehicle_id': d.vehicle_id,
            'filename': d.filename,
            'original_name': d.original_name,
            'notes': d.notes,
            'uploaded_at': d.uploaded_at
        })
    return result

# ========== INQUIRY FUNCTIONS ==========


def inquiry_create(data):
    inquiry = Inquiry(
        vehicle_id=data['vehicle_id'],
        dealer_id=data['dealer_id'],
        name=data['name'],
        email=data.get('email', ''),
        phone=data['phone'],
        message=data.get('message', ''),
        inquiry_type=data.get('inquiry_type', 'general'),
        status='pending'
    )
    db.session.add(inquiry)
    db.session.commit()
    return inquiry.id


def inquiry_update_status(inquiry_id, status):
    inquiry = Inquiry.query.get(inquiry_id)
    if inquiry:
        inquiry.status = status
        db.session.commit()
        return True
    return False


def inquiries_get_by_dealer(dealer_id):
    # Show a dealer ONLY the inquiries for vehicles they themselves uploaded.
    # Vehicles carry a dealer_id (set when the dealer lists them). We join
    # Inquiry → Vehicle and keep only rows where Vehicle.dealer_id matches.
    # Inquiries on vehicles that belong to a different dealer, or vehicles with
    # no dealer owner, are excluded — the dealer should not see those.
    from models import Vehicle
    inquiries = (
        Inquiry.query
        .join(Vehicle, Inquiry.vehicle_id == Vehicle.id)
        .filter(Vehicle.dealer_id == dealer_id)
        .order_by(Inquiry.created_at.desc())
        .all()
    )
    result = []
    for inq in inquiries:
        inq_dict = {
            'id': inq.id,
            'name': inq.name,
            'email': inq.email,
            'phone': inq.phone,
            'message': inq.message,
            'inquiry_type': inq.inquiry_type,
            'status': inq.status,
            'created_at': inq.created_at,
            'dealer_id': inq.dealer_id,
            'vehicle': vehicle_get(inq.vehicle_id) if inq.vehicle_id else None
        }
        result.append(inq_dict)
    return result


def init_db():
    db.create_all()


# ============================================================
# CENTRALIZED DOCUMENT STORAGE FUNCTIONS
# ============================================================

def cds_register(data: dict) -> int:
    """
    Register any uploaded file into the Central Document Storage.
    Call this immediately after saving a file to disk.

    Required keys: file_name, file_path, module_name
    Optional keys: dealer_id, original_name, document_type, uploaded_by,
                   performed_by, user_role
    Returns the new CentralDocumentStorage record id.
    """
    from models import CentralDocumentStorage, CentralDocumentAuditLog, User

    record = CentralDocumentStorage(
        dealer_id     = data.get('dealer_id'),
        file_name     = data['file_name'],
        original_name = data.get('original_name', data['file_name']),
        file_path     = data['file_path'],
        module_name   = data.get('module_name', 'Documents'),
        document_type = data.get('document_type', ''),
        uploaded_by   = data.get('uploaded_by'),
        status        = 'active',
    )
    db.session.add(record)
    db.session.flush()   # get record.id before committing

    # Snapshot dealer name for audit
    dealer_name = None
    if data.get('dealer_id'):
        d = User.query.get(data['dealer_id'])
        if d:
            dealer_name = d.name

    audit = CentralDocumentAuditLog(
        document_id   = record.id,
        action        = 'uploaded',
        performed_by  = data.get('performed_by', 'system'),
        user_role     = data.get('user_role', 'System'),
        dealer_name   = dealer_name,
        document_type = data.get('document_type', ''),
        notes         = f"Uploaded via {data.get('module_name', 'Documents')} module",
    )
    db.session.add(audit)
    db.session.commit()
    return record.id


def cds_list_all(filters: dict = None) -> list:
    """Return all CDS records (admin view). Optionally filter by status/module/dealer_id."""
    from models import CentralDocumentStorage

    q = CentralDocumentStorage.query

    if filters:
        if filters.get('status') and filters['status'] != 'all':
            q = q.filter(CentralDocumentStorage.status == filters['status'])
        if filters.get('module_name'):
            q = q.filter(CentralDocumentStorage.module_name == filters['module_name'])
        if filters.get('dealer_id'):
            q = q.filter(CentralDocumentStorage.dealer_id == filters['dealer_id'])
        if filters.get('search'):
            term = f"%{filters['search']}%"
            q = q.filter(
                db.or_(
                    CentralDocumentStorage.file_name.ilike(term),
                    CentralDocumentStorage.original_name.ilike(term),
                    CentralDocumentStorage.document_type.ilike(term),
                )
            )

    records = q.order_by(CentralDocumentStorage.created_at.desc()).all()
    return records


def cds_get(record_id: int):
    """Fetch single CDS record."""
    from models import CentralDocumentStorage
    return CentralDocumentStorage.query.get(record_id)



def cds_reassign(record_id: int, new_dealer_id: int, note: str,
                 performed_by: str = 'admin', user_role: str = 'Super Admin') -> bool:
    """
    Reassign a single document's ownership to a different dealer.

    Business rules enforced:
      - Document must exist and be 'active' (cannot reassign a deleted doc)
      - new_dealer_id must differ from current dealer_id
      - note must be non-empty (caller validates; we enforce here too)
    On success:
      - rec.dealer_id  → new_dealer_id
      - rec.ownership_note → note
      - Audit log entry with full dealer name / display_id snapshots
    The original dealer instantly loses visibility (dealer_id changed).
    The new dealer instantly gains visibility (their active docs include it).
    File on disk is NOT moved or renamed.
    """
    from models import CentralDocumentStorage, CentralDocumentAuditLog, User

    rec        = CentralDocumentStorage.query.get(record_id)
    new_dealer = User.query.get(new_dealer_id)

    # Guard: record / new dealer must exist
    if not rec or not new_dealer:
        return False

    # Guard: cannot reassign deleted document
    if rec.status == 'deleted':
        return False

    # Guard: must be a different dealer
    old_dealer_id = rec.dealer_id
    if old_dealer_id == new_dealer_id:
        return False

    # Guard: note mandatory
    if not note or not note.strip():
        return False

    # Snapshot old dealer info for audit
    old_dealer = User.query.get(old_dealer_id) if old_dealer_id else None
    old_dealer_name    = old_dealer.name        if old_dealer else 'Unknown'
    old_display_id     = (old_dealer.display_id or f'D{old_dealer_id}') if old_dealer else str(old_dealer_id)
    new_dealer_name    = new_dealer.name
    new_display_id     = new_dealer.display_id or f'D{new_dealer_id}'

    # Perform the reassignment
    rec.dealer_id      = new_dealer_id
    rec.ownership_note = note.strip()

    audit = CentralDocumentAuditLog(
        document_id   = rec.id,
        action        = 'reassigned',
        performed_by  = performed_by,
        user_role     = user_role,
        dealer_name   = new_dealer_name,
        document_type = rec.document_type,
        notes         = (
            f"Reassigned from {old_dealer_name} ({old_display_id}) "
            f"→ {new_dealer_name} ({new_display_id}). "
            f"Reason: {note.strip()}"
        ),
    )
    db.session.add(audit)
    db.session.commit()
    return True


def cds_soft_delete(record_id: int, performed_by: str = 'admin', user_role: str = 'Super Admin') -> bool:
    """Soft-delete (mark as deleted; file is NOT removed from disk)."""
    from models import CentralDocumentStorage, CentralDocumentAuditLog

    rec = CentralDocumentStorage.query.get(record_id)
    if not rec:
        return False
    if rec.status == 'deleted':
        return False  # already deleted

    rec.status = 'deleted'
    audit = CentralDocumentAuditLog(
        document_id   = rec.id,
        action        = 'deleted',
        performed_by  = performed_by,
        user_role     = user_role,
        dealer_name   = rec.dealer.name if rec.dealer else None,
        document_type = rec.document_type,
        notes         = 'Soft-deleted by admin.',
    )
    db.session.add(audit)
    db.session.commit()
    return True


def cds_hard_delete(record_id: int, upload_folder: str, performed_by: str = 'admin') -> bool:
    """Permanently delete the DB record AND the physical file from disk."""
    import os
    from models import CentralDocumentStorage, CentralDocumentAuditLog
    from datetime import datetime

    rec = CentralDocumentStorage.query.get(record_id)
    if not rec:
        return False

    # Delete physical file
    full_path = os.path.join(upload_folder, rec.file_name)
    if os.path.exists(full_path):
        os.remove(full_path)

    # Log before deleting the record
    audit = CentralDocumentAuditLog(
        document_id  = None,  # record being deleted
        action       = 'hard_deleted',
        performed_by = performed_by,
        notes        = f"Permanently deleted file: {rec.file_name} (module: {rec.module_name})",
    )
    db.session.add(audit)
    db.session.delete(rec)
    db.session.commit()
    return True


def cds_get_audit_logs(document_id: int = None) -> list:
    """Return audit logs for a specific document (or all if document_id is None)."""
    from models import CentralDocumentAuditLog
    q = CentralDocumentAuditLog.query
    if document_id:
        q = q.filter(CentralDocumentAuditLog.document_id == document_id)
    return q.order_by(CentralDocumentAuditLog.created_at.desc()).all()


def reassign_display_ids(role: str = None) -> None:
    """
    PERMANENT DEALER ID ENFORCEMENT
    ════════════════════════════════
    This function NO LONGER renumbers dealers — doing so would break the
    permanent-ID guarantee (a deleted D3 would be reassigned to a new dealer).

    Instead it works in ASSIGN-ONLY mode:
      • If a dealer/user already has a display_id  →  leave it unchanged.
      • If a dealer/user is missing a display_id   →  assign the next unused number.

    The result is that IDs are always gapless from 1 … current_max  for NEW
    additions, but existing IDs (including those belonging to suspended or
    soft-deleted dealers) are NEVER touched.

    Dealer ID Lifecycle guarantees preserved:
      ✓ D3 suspended  → D3 stays D3 forever
      ✓ D3 deleted    → D3 stays D3; new dealer gets D5 (or next unused)
      ✓ D3 reactivated → D3 still has display_id = D3
      ✓ New dealer    → gets max(all existing D-numbers) + 1
    """
    from models import User
    from sqlalchemy import text

    # Ensure display_id column exists (safety for fresh DBs)
    # Uses information_schema instead of SQLite PRAGMA table_info
    try:
        with db.engine.connect() as conn:
            _col_exists = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'display_id'
            """)).scalar()
            if not _col_exists:
                conn.execute(text("ALTER TABLE users ADD COLUMN display_id TEXT"))
                conn.commit()
    except Exception:
        pass

    roles_to_process = []
    if role in (None, 'dealer'):
        roles_to_process.append(('dealer', 'D'))
    if role in (None, 'user'):
        roles_to_process.append(('user', 'U'))

    for r, prefix in roles_to_process:
        # Collect ALL existing numbers for this role (including any gaps)
        existing_nums = set()
        for rec in User.query.filter_by(role=r).all():
            if rec.display_id and rec.display_id.startswith(prefix):
                try:
                    existing_nums.add(int(rec.display_id[len(prefix):]))
                except (ValueError, TypeError):
                    pass

        # Only assign IDs to records that don't have one yet
        next_num = (max(existing_nums) + 1) if existing_nums else 1
        records_needing_id = (
            User.query
            .filter_by(role=r)
            .filter(
                db.or_(User.display_id == None, User.display_id == '')
            )
            .order_by(User.created_at.asc(), User.id.asc())
            .all()
        )
        for rec in records_needing_id:
            # Skip over any number already taken
            while next_num in existing_nums:
                next_num += 1
            rec.display_id = f"{prefix}{next_num}"
            existing_nums.add(next_num)
            next_num += 1

    db.session.commit()


def cds_dealer_active_docs(dealer_id: int) -> list:
    """Return active CDS records assigned to a dealer BY admin only.
    Excludes documents the dealer uploaded themselves so they don't appear
    twice (once here and once in the dealer's own Documents table).
    """
    from models import CentralDocumentStorage
    return CentralDocumentStorage.query.filter(
        CentralDocumentStorage.dealer_id == dealer_id,
        CentralDocumentStorage.status == 'active',
        # Only show docs that were NOT uploaded by the dealer themselves
        db.or_(
            CentralDocumentStorage.uploaded_by == None,
            CentralDocumentStorage.uploaded_by != dealer_id,
        ),
    ).order_by(CentralDocumentStorage.created_at.desc()).all()

