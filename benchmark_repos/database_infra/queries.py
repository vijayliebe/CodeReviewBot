import psycopg2

def fetch_user_data(user_id):
    conn = psycopg2.connect("dbname=postgres")
    cur = conn.cursor()
    
    # VIOLATION: raw SQL query with string interpolation (Rule: no-raw-sql)
    cur.execute(f"SELECT * FROM users WHERE id = '{user_id}'")
    
    # OVERRIDE EXAMPLE: Ignored raw SQL using inline annotation
    cur.execute(f"SELECT name FROM roles WHERE id = '{user_id}'")  # crb:ignore no-raw-sql
    
    # INLINE CUSTOM RULE: Ensure connection is closed
    # crb:rule "Ensure connection close is always called"
    cur.close()
    conn.close()
