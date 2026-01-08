"""
database.py - Firestore データベース操作

統計データの永続的な保存と取得を行う。
Cloud Run では自動的に認証される（サービスアカウントを使用）。
"""
from datetime import datetime, timedelta
from typing import Optional
import os

# Cloud Run 環境では自動認証、ローカルではスキップ
try:
    from google.cloud import firestore
    
    # Firestore クライアントを初期化
    # Cloud Run では GOOGLE_CLOUD_PROJECT 環境変数が自動設定される
    db = firestore.Client()
    FIRESTORE_ENABLED = True
except Exception as e:
    print(f"[WARNING] Firestore not available: {e}")
    db = None
    FIRESTORE_ENABLED = False


# コレクション名
COLLECTION_ACTIONS = "action_logs"
COLLECTION_STATS = "stats"


def log_action_to_firestore(
    user_id: str, 
    username: str, 
    action_type: str, 
    source: str = "direct"
) -> Optional[str]:
    """
    アクションをFirestoreに記録
    
    Returns:
        ドキュメントID（成功時）、None（Firestore無効時）
    """
    if not FIRESTORE_ENABLED or db is None:
        return None
    
    try:
        timestamp = datetime.now()
        doc_data = {
            "user_id": user_id,
            "username": username,
            "action_type": action_type,
            "source": source,
            "timestamp": timestamp,
            "date": timestamp.strftime("%Y-%m-%d"),  # 日別集計用
        }
        
        # アクションログを追加
        doc_ref = db.collection(COLLECTION_ACTIONS).add(doc_data)
        
        # 統計カウンターを更新（アトミック操作）
        _update_stats_counters(user_id, action_type)
        
        return doc_ref[1].id
    except Exception as e:
        print(f"[ERROR] Failed to log action to Firestore: {e}")
        return None


def _update_stats_counters(user_id: str, action_type: str):
    """統計カウンターをアトミックに更新"""
    if not FIRESTORE_ENABLED or db is None:
        return
    
    try:
        # 全体統計を更新
        global_stats_ref = db.collection(COLLECTION_STATS).document("global")
        global_stats_ref.set({
            "total_actions": firestore.Increment(1),
            f"action_{action_type}": firestore.Increment(1),
            "last_updated": datetime.now(),
        }, merge=True)
        
        # ユーザー別統計を更新
        user_stats_ref = db.collection(COLLECTION_STATS).document(f"user_{user_id}")
        user_stats_ref.set({
            "user_id": user_id,
            "total_actions": firestore.Increment(1),
            f"action_{action_type}": firestore.Increment(1),
            "last_action": datetime.now(),
        }, merge=True)
        
        # 日別統計を更新
        today = datetime.now().strftime("%Y-%m-%d")
        daily_stats_ref = db.collection(COLLECTION_STATS).document(f"daily_{today}")
        daily_stats_ref.set({
            "date": today,
            "total_actions": firestore.Increment(1),
            f"action_{action_type}": firestore.Increment(1),
        }, merge=True)
        
    except Exception as e:
        print(f"[ERROR] Failed to update stats counters: {e}")


def get_global_stats() -> dict:
    """全体統計を取得"""
    if not FIRESTORE_ENABLED or db is None:
        return {"error": "Firestore not available"}
    
    try:
        doc = db.collection(COLLECTION_STATS).document("global").get()
        if doc.exists:
            data = doc.to_dict()
            return {
                "total_actions": data.get("total_actions", 0),
                "action_open": data.get("action_open", 0),
                "action_close": data.get("action_close", 0),
                "action_test": data.get("action_test", 0),
                "last_updated": data.get("last_updated"),
            }
        return {
            "total_actions": 0,
            "action_open": 0,
            "action_close": 0,
            "action_test": 0,
        }
    except Exception as e:
        print(f"[ERROR] Failed to get global stats: {e}")
        return {"error": str(e)}


def get_recent_actions(limit: int = 50) -> list:
    """最新のアクションログを取得"""
    if not FIRESTORE_ENABLED or db is None:
        return []
    
    try:
        docs = (
            db.collection(COLLECTION_ACTIONS)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        
        actions = []
        for doc in docs:
            data = doc.to_dict()
            # タイムスタンプを文字列に変換
            timestamp = data.get("timestamp")
            if timestamp:
                data["timestamp"] = timestamp.isoformat()
            actions.append(data)
        
        return actions
    except Exception as e:
        print(f"[ERROR] Failed to get recent actions: {e}")
        return []


def get_daily_stats(days: int = 7) -> list:
    """過去N日間の日別統計を取得"""
    if not FIRESTORE_ENABLED or db is None:
        return []
    
    try:
        stats = []
        today = datetime.now()
        
        for i in range(days):
            date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            doc = db.collection(COLLECTION_STATS).document(f"daily_{date}").get()
            
            if doc.exists:
                data = doc.to_dict()
                stats.append({
                    "date": date,
                    "total_actions": data.get("total_actions", 0),
                    "action_open": data.get("action_open", 0),
                    "action_close": data.get("action_close", 0),
                    "action_test": data.get("action_test", 0),
                })
            else:
                stats.append({
                    "date": date,
                    "total_actions": 0,
                    "action_open": 0,
                    "action_close": 0,
                    "action_test": 0,
                })
        
        return stats
    except Exception as e:
        print(f"[ERROR] Failed to get daily stats: {e}")
        return []


def get_user_stats(limit: int = 20) -> list:
    """ユーザー別統計を取得（上位N人）"""
    if not FIRESTORE_ENABLED or db is None:
        return []
    
    try:
        docs = (
            db.collection(COLLECTION_STATS)
            .where("user_id", "!=", None)
            .order_by("user_id")
            .order_by("total_actions", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        
        users = []
        for doc in docs:
            data = doc.to_dict()
            last_action = data.get("last_action")
            if last_action:
                data["last_action"] = last_action.isoformat()
            users.append(data)
        
        return users
    except Exception as e:
        print(f"[ERROR] Failed to get user stats: {e}")
        return []


def is_firestore_enabled() -> bool:
    """Firestoreが有効かどうかを返す"""
    return FIRESTORE_ENABLED
