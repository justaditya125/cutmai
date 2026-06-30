"""
MySQL Database configuration - Wrapper that exposes a dict-based query API
over MySQL tables, with find/insert/update/delete operations.
"""
import secrets
import time
import threading
import re
from datetime import datetime
from botai.config import settings


def generate_id():
    """Generate a 24-char hex ID for MySQL primary keys"""
    return secrets.token_hex(12)


def _sanitize_column(name: str) -> str:
    """Validate a column name contains only safe characters (alphanumeric + underscore).
    Raises ValueError on injection attempts."""
    if not isinstance(name, str) or not name:
        raise ValueError(f"Invalid column name: {name}")
    if not re.fullmatch(r'[A-Za-z0-9_]+', name):
        raise ValueError(f"Invalid column name: {name}")
    if name.startswith('_') and name != '_id':
        raise ValueError(f"Invalid column name: {name}")
    return name


class DatabaseError(Exception):
    pass


class InsertOneResult:
    """Mimics MySQL's insert_one result"""
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class Cursor:
    """Mimics MySQL cursor with .sort().limit() chaining"""
    def __init__(self, collection, filter=None, projection=None):
        self._collection = collection
        self._filter = filter or {}
        self._projection = projection
        self._sort = None
        self._limit_val = None
        self._skip_val = None
        self._results = None

    def sort(self, field, direction=1):
        self._sort = (field, 'DESC' if direction < 0 else 'ASC')
        return self

    def limit(self, n):
        self._limit_val = n
        return self

    def skip(self, n):
        self._skip_val = n
        return self

    def _execute(self):
        if self._results is None:
            query, params = self._collection._build_select(
                filter=self._filter,
                projection=self._projection,
                sort=self._sort,
                limit=self._limit_val,
                offset=self._skip_val
            )
            self._results = self._collection._execute_query(query, params)
        return self._results

    def __iter__(self):
        return iter(self._execute())

    def __len__(self):
        return len(self._execute())

    def __bool__(self):
        return bool(self._execute())

    def __getitem__(self, idx):
        return self._execute()[idx]

    def count(self):
        return len(self._execute())


class Collection:
    """Mimics a MySQL collection but uses MySQL tables"""

    def __init__(self, db, table_name):
        self._db = db
        self._table = table_name

    def _to_filter_sql(self, filter_dict):
        """Convert MySQL filter dict to SQL WHERE clause and params."""
        clauses = []
        params = []
        for key, value in filter_dict.items():
            col = 'id' if key == '_id' else _sanitize_column(key)
            if isinstance(value, dict):
                for op, val in value.items():
                    if op == '$gte':
                        clauses.append(f"{col} >= %s")
                        params.append(val)
                    elif op == '$gt':
                        clauses.append(f"{col} > %s")
                        params.append(val)
                    elif op == '$lte':
                        clauses.append(f"{col} <= %s")
                        params.append(val)
                    elif op == '$lt':
                        clauses.append(f"{col} < %s")
                        params.append(val)
                    elif op == '$ne':
                        if val is None:
                            clauses.append(f"{col} IS NOT NULL")
                        else:
                            clauses.append(f"{col} != %s")
                            params.append(val)
                    elif op == '$in':
                        placeholders = ', '.join(['%s'] * len(val))
                        clauses.append(f"{col} IN ({placeholders})")
                        params.extend(val)
                    elif op == '$nin':
                        placeholders = ', '.join(['%s'] * len(val))
                        clauses.append(f"{col} NOT IN ({placeholders})")
                        params.extend(val)
                    elif op == '$exists':
                        if val:
                            clauses.append(f"{col} IS NOT NULL")
                        else:
                            clauses.append(f"{col} IS NULL")
                    elif op == '$regex':
                        clauses.append(f"{col} REGEXP %s")
                        params.append(val)
                    elif op == '$options':
                        pass
                    else:
                        clauses.append(f"{col} = %s")
                        params.append(val)
            else:
                if value is None:
                    clauses.append(f"{col} IS NULL")
                else:
                    clauses.append(f"{col} = %s")
                    params.append(value)
        return ' AND '.join(clauses), params

    def _build_select(self, filter=None, projection=None, sort=None, limit=None, offset=None):
        if projection:
            cols = []
            include_mode = any(v == 1 for v in projection.values() if isinstance(v, int))
            for k, v in projection.items():
                col = 'id' if k == '_id' else _sanitize_column(k)
                if include_mode:
                    if v == 1:
                        cols.append(col)
                else:
                    if v != 0:
                        cols.append(col)
            select = ', '.join(cols) if cols else '*'
        else:
            select = '*'

        query = f"SELECT {select} FROM {self._table}"
        params = []

        if filter:
            where, p = self._to_filter_sql(filter)
            if where:
                query += f" WHERE {where}"
                params = p

        if sort:
            field, direction = sort
            col = 'id' if field == '_id' else _sanitize_column(field)
            query += f" ORDER BY {col} {direction}"

        if limit:
            query += f" LIMIT {limit}"

        if offset:
            query += f" OFFSET {offset}"

        return query, params

    def _row_to_doc(self, row):
        """Convert MySQL row to MySQL-compatible document (_id not id)"""
        if row is None:
            return None
        doc = {}
        for k, v in row.items():
            if k == 'id':
                doc['_id'] = v
                doc['id'] = v
            else:
                doc[k] = v
        return doc

    def _rows_to_docs(self, rows):
        return [self._row_to_doc(r) for r in rows]

    def _execute_query(self, query, params):
        """Execute a SELECT query with automatic retry on connection failure."""
        for attempt in range(2):
            try:
                conn = self._db.get_connection()
                cursor = conn.cursor(dictionary=True)
                try:
                    cursor.execute(query, params)
                    rows = cursor.fetchall()
                    conn.commit()
                    return self._rows_to_docs(rows)
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    raise
                finally:
                    cursor.close()
            except Exception as e:
                if attempt == 0:
                    # Force reconnect and retry once
                    try:
                        self._db.force_reconnect()
                    except Exception:
                        pass
                    continue
                raise DatabaseError(f"Query error on {self._table}: {e}") from e

    def _execute_update(self, query, params):
        """Execute an INSERT/UPDATE/DELETE query with automatic retry on connection failure."""
        for attempt in range(2):
            try:
                conn = self._db.get_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute(query, params)
                    conn.commit()
                    rowcount = cursor.rowcount
                    return rowcount
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    raise
                finally:
                    cursor.close()
            except Exception as e:
                if attempt == 0:
                    try:
                        self._db.force_reconnect()
                    except Exception:
                        pass
                    continue
                raise DatabaseError(f"Update error on {self._table}: {e}") from e

    def find_one(self, filter=None, projection=None, sort=None):
        sort_tuple = None
        if sort:
            if isinstance(sort, list) and len(sort) > 0:
                field, direction = sort[0]
                sort_tuple = (field, 'DESC' if direction < 0 else 'ASC')
            elif isinstance(sort, tuple):
                field, direction = sort
                sort_tuple = (field, 'DESC' if direction < 0 else 'ASC')
        query, params = self._build_select(filter=filter, projection=projection, sort=sort_tuple, limit=1)
        rows = self._execute_query(query, params)
        return rows[0] if rows else None

    def find(self, filter=None, projection=None):
        return Cursor(self, filter=filter, projection=projection)

    def insert_one(self, document):
        doc = dict(document)
        if '_id' not in doc or doc['_id'] is None:
            doc['_id'] = generate_id()
        doc_id = doc.pop('_id')
        doc['id'] = doc_id

        safe_keys = [_sanitize_column(k) for k in doc.keys()]
        columns = ', '.join(safe_keys)
        placeholders = ', '.join(['%s'] * len(doc))
        query = f"INSERT INTO {self._table} ({columns}) VALUES ({placeholders})"
        self._execute_update(query, list(doc.values()))
        return InsertOneResult(doc_id)

    def insert_many(self, documents):
        ids = []
        for doc in documents:
            result = self.insert_one(doc)
            ids.append(result.inserted_id)
        return ids

    def update_one(self, filter, update_data):
        set_clauses = []
        inc_clauses = []
        unset_clauses = []
        params = []

        if isinstance(update_data, dict):
            if '$set' in update_data:
                for key, value in update_data['$set'].items():
                    col = 'id' if key == '_id' else _sanitize_column(key)
                    if value is None:
                        set_clauses.append(f"{col} = NULL")
                    else:
                        set_clauses.append(f"{col} = %s")
                        params.append(value)

            if '$inc' in update_data:
                for key, value in update_data['$inc'].items():
                    col = 'id' if key == '_id' else _sanitize_column(key)
                    inc_clauses.append(f"{col} = {col} + %s")
                    params.append(value)

            if '$unset' in update_data:
                for key in update_data['$unset']:
                    col = 'id' if key == '_id' else _sanitize_column(key)
                    unset_clauses.append(f"{col} = NULL")

            if '$push' in update_data:
                for key, value in update_data['$push'].items():
                    col = 'id' if key == '_id' else _sanitize_column(key)
                    set_clauses.append(f"{col} = JSON_ARRAY_APPEND({col}, '$', %s)")
                    params.append(value)

        all_clauses = set_clauses + inc_clauses + unset_clauses
        if not all_clauses:
            return None

        set_sql = ', '.join(all_clauses)
        where_sql, where_params = self._to_filter_sql(filter)
        query = f"UPDATE {self._table} SET {set_sql} WHERE {where_sql} LIMIT 1"
        params.extend(where_params)
        return self._execute_update(query, params)

    def update_many(self, filter, update_data):
        set_clauses = []
        inc_clauses = []
        unset_clauses = []
        params = []

        if isinstance(update_data, dict):
            if '$set' in update_data:
                for key, value in update_data['$set'].items():
                    col = 'id' if key == '_id' else _sanitize_column(key)
                    if value is None:
                        set_clauses.append(f"{col} = NULL")
                    else:
                        set_clauses.append(f"{col} = %s")
                        params.append(value)

            if '$inc' in update_data:
                for key, value in update_data['$inc'].items():
                    col = 'id' if key == '_id' else _sanitize_column(key)
                    inc_clauses.append(f"{col} = {col} + %s")
                    params.append(value)

            if '$unset' in update_data:
                for key in update_data['$unset']:
                    col = 'id' if key == '_id' else _sanitize_column(key)
                    unset_clauses.append(f"{col} = NULL")

            if '$push' in update_data:
                for key, value in update_data['$push'].items():
                    col = 'id' if key == '_id' else _sanitize_column(key)
                    set_clauses.append(f"{col} = JSON_ARRAY_APPEND({col}, '$', %s)")
                    params.append(value)

        all_clauses = set_clauses + inc_clauses + unset_clauses
        if not all_clauses:
            return None

        set_sql = ', '.join(all_clauses)
        where_sql, where_params = self._to_filter_sql(filter)
        query = f"UPDATE {self._table} SET {set_sql} WHERE {where_sql}"
        params.extend(where_params)
        return self._execute_update(query, params)

    def find_one_and_delete(self, filter, sort=None):
        sort_tuple = None
        if sort:
            if isinstance(sort, list) and len(sort) > 0:
                field, direction = sort[0]
                sort_tuple = (field, 'DESC' if direction < 0 else 'ASC')
        query, params = self._build_select(filter=filter, sort=sort_tuple, limit=1)
        rows = self._execute_query(query, params)
        if rows:
            self.delete_one(filter)
            return rows[0]
        return None

    def delete_one(self, filter):
        where_sql, params = self._to_filter_sql(filter)
        query = f"DELETE FROM {self._table} WHERE {where_sql} LIMIT 1"
        return self._execute_update(query, params)

    def delete_many(self, filter):
        where_sql, params = self._to_filter_sql(filter)
        query = f"DELETE FROM {self._table} WHERE {where_sql}"
        return self._execute_update(query, params)

    def count_documents(self, filter=None):
        query = f"SELECT COUNT(*) as cnt FROM {self._table}"
        params = []
        if filter:
            where, p = self._to_filter_sql(filter)
            if where:
                query += f" WHERE {where}"
                params = p
        rows = self._execute_query(query, params)
        return rows[0]['cnt'] if rows else 0

    def _strip_dollar(self, val):
        if isinstance(val, str) and val.startswith('$'):
            return _sanitize_column(val[1:])
        if isinstance(val, str):
            return _sanitize_column(val)
        return val

    def aggregate(self, pipeline):
        """Simple aggregate support for $match + $group pipelines"""
        if not pipeline:
            return []

        match_stage = None
        group_stage = None

        for stage in pipeline:
            if '$match' in stage:
                match_stage = stage['$match']
            elif '$group' in stage:
                group_stage = stage['$group']

        select_cols = []
        group_cols = []
        params = []

        if group_stage:
            id_expr = group_stage.get('_id')
            if isinstance(id_expr, str) and id_expr.startswith('$'):
                field = _sanitize_column(id_expr[1:])
                select_cols.append(f'{field} as _id')
                group_cols.append(field)
            elif id_expr is None:
                pass
            else:
                select_cols.append(f'{id_expr} as _id')
                group_cols.append(id_expr)

            for key, agg in group_stage.items():
                if key == '_id':
                    continue
                if isinstance(agg, dict):
                    if '$sum' in agg:
                        val = agg['$sum']
                        if val == 1:
                            select_cols.append(f"COUNT(*) as `{_sanitize_column(key)}`")
                        else:
                            col = self._strip_dollar(val)
                            select_cols.append(f"COALESCE(SUM({col}), 0) as `{_sanitize_column(key)}`")
                    elif '$avg' in agg:
                        col = self._strip_dollar(agg['$avg'])
                        select_cols.append(f"AVG({col}) as `{_sanitize_column(key)}`")
                    elif '$first' in agg:
                        col = self._strip_dollar(agg['$first'])
                        select_cols.append(f"MIN({col}) as `{_sanitize_column(key)}`")
                    elif '$max' in agg:
                        col = self._strip_dollar(agg['$max'])
                        select_cols.append(f"MAX({col}) as `{_sanitize_column(key)}`")
                    elif '$min' in agg:
                        col = self._strip_dollar(agg['$min'])
                        select_cols.append(f"MIN({col}) as `{_sanitize_column(key)}`")

        query = f"SELECT {', '.join(select_cols) if select_cols else 'COUNT(*) as cnt'} FROM {self._table}"

        if match_stage:
            where, p = self._to_filter_sql(match_stage)
            if where:
                query += f" WHERE {where}"
                params = p

        if group_cols:
            query += f" GROUP BY {', '.join(group_cols)}"

        return self._execute_query(query, params)

    def create_index(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        if name in ('find', 'find_one', 'insert_one', 'insert_many', 'update_one',
                     'update_many', 'delete_one', 'delete_many', 'count_documents',
                     'aggregate', 'create_index'):
            return getattr(self, name)
        raise AttributeError(f"Collection has no attribute '{name}'")


class Database:
    """MySQL-compatible database wrapper. Uses per-thread connections for thread safety."""

    def __init__(self):
        self.config = {
            'host': settings.MYSQL_HOST,
            'port': settings.MYSQL_PORT,
            'user': settings.MYSQL_USER,
            'password': settings.MYSQL_PASSWORD,
            'database': settings.MYSQL_DATABASE,
            'charset': 'utf8mb4',
            'use_unicode': True,
            'autocommit': False,
        }
        self._local = threading.local()
        self._collections = {}
        self._PING_INTERVAL = 30  # seconds between health checks

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        if name not in self._collections:
            self._collections[name] = Collection(self, name)
        return self._collections[name]

    def _get_thread_conn(self):
        """Return the connection object for the current thread, or None."""
        return getattr(self._local, 'conn', None)

    def _set_thread_conn(self, conn):
        self._local.conn = conn
        self._local.last_ping = time.time()

    def get_connection(self):
        import mysql.connector
        conn = self._get_thread_conn()
        now = time.time()
        last_ping = getattr(self._local, 'last_ping', 0)

        if conn is not None:
            try:
                if not conn.is_connected() or (now - last_ping) > self._PING_INTERVAL:
                    conn.ping(reconnect=True, attempts=2, delay=1)
                    self._local.last_ping = now
                return conn
            except Exception:
                # Connection is dead — close and recreate
                try:
                    conn.close()
                except Exception:
                    pass

        # Create a new connection for this thread
        conn = mysql.connector.connect(**self.config)
        self._set_thread_conn(conn)
        return conn

    def force_reconnect(self):
        """Force-close and recreate the connection for the current thread."""
        import mysql.connector
        conn = self._get_thread_conn()
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        conn = mysql.connector.connect(**self.config)
        self._set_thread_conn(conn)
        return conn

    def command(self, cmd):
        if cmd == 'ping':
            conn = self.get_connection()
            conn.ping(reconnect=True, attempts=3, delay=2)
            return {'ok': 1}
        raise NotImplementedError(f"Command '{cmd}' not supported")

    def close(self):
        conn = self._get_thread_conn()
        if conn is not None:
            try:
                if conn.is_connected():
                    conn.close()
                    print("MySQL connection closed")
            except Exception:
                pass
        self._local.conn = None


_db = None
_client = None


def get_db():
    """Get MySQL database instance (MySQL-compatible API)"""
    global _db
    if _db is None:
        _db = Database()
        print(f"Connected to MySQL: {settings.MYSQL_DATABASE}@{settings.MYSQL_HOST}")
    return _db


def init_db():
    """Initialize database connection"""
    try:
        db = get_db()
        db.command('ping')
        print("MySQL database initialized")
        return True
    except Exception as e:
        print(f"MySQL initialization failed: {e}")
        return False


def close_db():
    """Close MySQL connection"""
    global _db, _client
    if _db is not None:
        _db.close()
    _db = None
    _client = None
