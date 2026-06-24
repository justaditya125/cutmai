"""
Admin routes
"""
import json
from datetime import datetime
from botai.config.MySQL_config import get_db
from botai.utils.logger import log_suspicious_activity
from botai.services.email_service import generate_monitoring_email_body, email_service

def handle_post(handler):
    path = handler.path
    if path == '/api/admin/stats':
        handle_admin_stats(handler)
    elif path == '/api/admin/approve_user':
        handle_approve_user(handler)
    elif path == '/api/admin/set_limit':
        handle_set_limit(handler)
    elif path == '/api/admin/send_monitoring_report':
        handle_send_monitoring_report(handler)
    else:
        handler.send_json(404, {'error': 'Not found'})

def handle_admin_stats(handler):
    data  = handler.read_body()
    token = data.get('session_token', '')
    user  = handler.get_user_from_token(token)
    
    if not user or not user.get('is_admin', False):
        client_ip = handler.get_client_ip()
        log_suspicious_activity(
            user.get('email', client_ip) if user else client_ip,
            "Unauthorized Admin Access",
            f"Attempted to access admin stats endpoint from IP {client_ip}",
            "HIGH"
        )
        return handler.send_json(403, {'error': 'Forbidden: Admin access required'})

    db = get_db()
    if db is None:
        return handler.send_json(500, {'error': 'Database unavailable'})
        
    try:
        # All users
        users = list(db.users.find())
        
        users_list = []
        for u in users:
            u_id = u['_id']
            conv_count = db.conversations.count_documents({"user_id": u_id})
            sess_count = db.user_sessions.count_documents({"user_id": u_id, "expires_at": {"$gt": datetime.now()}})
            
            u_ll = u.get("last_login")
            u_ca = u.get("created_at")
            
            # Calculate user credits
            credits = 0.0
            try:
                from botai.capabilities.model_orchestration.cost_estimator import cost_estimator
                user_tokens = db.token_usage.find({"user_id": u_id})
                for r in user_tokens:
                    m = r.get("model", "")
                    in_t = r.get("input_tokens", 0)
                    out_t = r.get("output_tokens", 0)
                    c_write = r.get("cache_creation_input_tokens", 0)
                    c_read = r.get("cache_read_input_tokens", 0)
                    
                    est = cost_estimator.estimate(m, in_t, out_t, c_write, c_read)
                    credits += est['total_cost']
            except Exception as ex:
                print(f"Error calculating credits for user {u_id}: {ex}")

            total_tokens = u.get("total_tokens_used") or 0
            limit = u.get("token_limit") or 1000000
            balance = max(0, limit - total_tokens)

            users_list.append({
                "id": u_id,
                "email": u.get("email"),
                "name": u.get("name"),
                "login_method": u.get("login_method", "email"),
                "is_approved": u.get("is_approved", False),
                "total_tokens_used": total_tokens,
                "token_limit": limit,
                "token_balance": balance,
                "credits_used": credits,
                "total_messages": u.get("total_messages") or 0,
                "last_login": u_ll.strftime('%Y-%m-%d %H:%M:%S') if isinstance(u_ll, datetime) else 'Never',
                "created_at": u_ca.strftime('%Y-%m-%d %H:%M:%S') if isinstance(u_ca, datetime) else '',
                "total_conversations": conv_count,
                "active_sessions": sess_count
            })
        
        # Sort users by total tokens descend (same as original view)
        users_list.sort(key=lambda x: x['total_tokens_used'], reverse=True)

        # Summary counts
        total_users = len(users_list)
        grand_total = sum(u.get("total_tokens_used") or 0 for u in users)
        total_msgs = sum(u.get("total_messages") or 0 for u in users)
        active_sessions = db.user_sessions.count_documents({"expires_at": {"$gt": datetime.now()}})
        total_convs = db.conversations.count_documents({})

        # Recent activity logs
        recent = list(db.token_usage.find().sort("created_at", -1).limit(20))
        recent_list = []
        for r in recent:
            user_doc = db.users.find_one({"_id": r['user_id']})
            email = user_doc['email'] if user_doc else 'unknown'
            r_ca = r.get("created_at")
            recent_list.append({
                "email": email,
                "input_tokens": r.get("input_tokens", 0),
                "output_tokens": r.get("output_tokens", 0),
                "total_tokens": r.get("total_tokens", 0),
                "created_at": r_ca.strftime('%Y-%m-%d %H:%M:%S') if isinstance(r_ca, datetime) else ''
            })

        # Active sessions
        sessions = list(db.user_sessions.find({"expires_at": {"$gt": datetime.now()}}).sort("created_at", -1))
        sessions_list = []
        for s in sessions:
            user_doc = db.users.find_one({"_id": s['user_id']})
            email = user_doc['email'] if user_doc else 'unknown'
            name = user_doc['name'] if user_doc else '-'
            s_ca = s.get("created_at")
            s_ea = s.get("expires_at")
            sessions_list.append({
                "email": email,
                "name": name,
                "ip_address": s.get("ip_address", "unknown"),
                "created_at": s_ca.strftime('%Y-%m-%d %H:%M:%S') if isinstance(s_ca, datetime) else '',
                "expires_at": s_ea.strftime('%Y-%m-%d %H:%M:%S') if isinstance(s_ea, datetime) else ''
            })

        handler.send_json(200, {
            'users': users_list,
            'summary': {
                'total_users': total_users,
                'grand_total_tokens': int(grand_total),
                'total_messages': int(total_msgs),
                'active_sessions': active_sessions,
                'total_conversations': total_convs
            },
            'recent_activity': recent_list,
            'active_sessions': sessions_list
        })
    except Exception as e:
        print(f"[ERROR] Admin stats error: {e}")
        handler.send_json(500, {'error': str(e)})

def handle_approve_user(handler):
    data   = handler.read_body()
    token  = data.get('session_token', '')
    user   = handler.get_user_from_token(token)
    
    if not user or not user.get('is_admin', False):
        client_ip = handler.get_client_ip()
        log_suspicious_activity(
            user.get('email', client_ip) if user else client_ip,
            "Unauthorized User Approval",
            f"Attempted to approve user from IP {client_ip}",
            "HIGH"
        )
        return handler.send_json(403, {'error': 'Forbidden: Admin access required'})

    target_user_id = data.get('target_user_id', '')
    action         = data.get('action', '') # 'approve', 'revoke', or 'reject'

    if not target_user_id or action not in ['approve', 'revoke', 'reject']:
        return handler.send_json(400, {'error': 'Missing target_user_id or valid action'})

    db = get_db()
    if db is None:
        return handler.send_json(500, {'error': 'Database unavailable'})

    try:
        t_id = target_user_id
        
        # Prevent admin from revoking themselves
        if t_id == user['id'] and action == 'revoke':
            return handler.send_json(400, {'error': 'You cannot revoke your own approval status'})

        if action == 'reject':
            db.users.delete_one({"_id": t_id})
            db.user_sessions.delete_many({"user_id": t_id})
            conv_ids = [c['_id'] for c in db.conversations.find({"user_id": t_id}, {"_id": 1})]
            if conv_ids:
                for cid in conv_ids:
                    db.messages.delete_many({"conversation_id": cid})
            db.conversations.delete_many({"user_id": t_id})
            print(f"[ADMIN] Rejected (deleted) user ID: {target_user_id}")
        else:
            is_approved = (action == 'approve')
            db.users.update_one(
                {"_id": t_id},
                {"$set": {"is_approved": is_approved, "updated_at": datetime.now()}}
            )

            # If revoked, delete all active sessions for that user immediately to kick them out
            if not is_approved:
                db.user_sessions.delete_many({"user_id": t_id})
                print(f"[ADMIN] Revoked approval and terminated sessions for user ID: {target_user_id}")
            else:
                print(f"[ADMIN] Approved user ID: {target_user_id}")

        handler.send_json(200, {'success': True})
    except Exception as e:
        print(f"[ERROR] Approve user error: {e}")
        handler.send_json(500, {'error': str(e)})

def handle_set_limit(handler):
    data  = handler.read_body()
    token = data.get('session_token', '')
    user  = handler.get_user_from_token(token)
    
    if not user or not user.get('is_admin', False):
        client_ip = handler.get_client_ip()
        log_suspicious_activity(
            user.get('email', client_ip) if user else client_ip,
            "Unauthorized Limit Change",
            f"Attempted to set token limit from IP {client_ip}",
            "HIGH"
        )
        return handler.send_json(403, {'error': 'Forbidden: Admin access required'})

    target_user_id = data.get('target_user_id', '')
    new_limit      = data.get('token_limit')

    if not target_user_id or new_limit is None:
        return handler.send_json(400, {'error': 'Missing target_user_id or token_limit'})

    try:
        new_limit = int(new_limit)
        if new_limit < 0:
            return handler.send_json(400, {'error': 'Token limit must be a positive integer'})
    except ValueError:
        return handler.send_json(400, {'error': 'Token limit must be a valid integer'})

    db = get_db()
    if db is None:
        return handler.send_json(500, {'error': 'Database unavailable'})

    try:
        t_id = target_user_id
        
        db.users.update_one(
            {"_id": t_id},
            {"$set": {"token_limit": new_limit, "updated_at": datetime.now()}}
        )
        print(f"[ADMIN] Set token limit to {new_limit} for user ID: {target_user_id}")
        handler.send_json(200, {'success': True})
    except Exception as e:
        print(f"[ERROR] Set limit error: {e}")
        handler.send_json(500, {'error': str(e)})

def handle_send_monitoring_report(handler):
    data  = handler.read_body()
    token = data.get('session_token', '')
    user  = handler.get_user_from_token(token)
    
    if not user or not user.get('is_admin', False):
        client_ip = handler.get_client_ip()
        log_suspicious_activity(
            user.get('email', client_ip) if user else client_ip,
            "Unauthorized Admin Access",
            f"Attempted to trigger status report email from IP {client_ip}",
            "HIGH"
        )
        return handler.send_json(403, {'error': 'Forbidden: Admin access required'})

    try:
        subject = f"[MONITOR] Manual Status Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        body = generate_monitoring_email_body()
        
        # Send in background non-blocking
        email_service.send_email_in_background(subject, body)
        
        handler.send_json(200, {
            'success': True,
            'message': 'Monitoring report email triggered successfully in the background.'
        })
    except Exception as e:
        print(f"[ERROR] Failed manual trigger: {e}")
        handler.send_json(500, {'error': str(e)})
