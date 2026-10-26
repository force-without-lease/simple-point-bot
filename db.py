import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    guild INTEGER, user INTEGER, xp INTEGER DEFAULT 0, points INTEGER DEFAULT 0,
    PRIMARY KEY (guild, user));
CREATE INDEX IF NOT EXISTS users_xp ON users(guild, xp DESC);
CREATE TABLE IF NOT EXISTS settings(
    guild INTEGER PRIMARY KEY,
    announce TEXT NOT NULL DEFAULT 'current',
    announce_channel INTEGER,
    message TEXT NOT NULL DEFAULT '{user} 님이 레벨 {level}에 도달했습니다. (+{points} 포인트)',
    xp_rate REAL NOT NULL DEFAULT 1.0,
    voice_xp INTEGER NOT NULL DEFAULT 10,
    level_points INTEGER NOT NULL DEFAULT 100,
    stack_roles INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS level_roles(
    guild INTEGER, level INTEGER, role INTEGER, PRIMARY KEY (guild, level));
CREATE TABLE IF NOT EXISTS no_xp(
    guild INTEGER, target INTEGER, kind TEXT, PRIMARY KEY (guild, target));
"""

SETTING_FIELDS = {"announce", "announce_channel", "message", "xp_rate", "voice_xp", "level_points", "stack_roles"}
BOARD_COLUMNS = {"xp", "points"}

conn: sqlite3.Connection


def open_db(path):
    global conn
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)


# MEE6 공식: 레벨 L 에서 L+1 로 가는 데 5L² + 50L + 100
def xp_to_next(level):
    return 5 * level * level + 50 * level + 100


def level_progress(total):
    level = 0
    while total >= (need := xp_to_next(level)):
        total -= need
        level += 1
    return level, total, need


def level_of(total):
    return level_progress(total)[0]


def get_user(guild, user):
    return conn.execute("SELECT xp, points FROM users WHERE guild=? AND user=?", (guild, user)).fetchone() or (0, 0)


def add_xp(guild, user, amount, level_points):
    with conn:
        conn.execute("INSERT OR IGNORE INTO users(guild, user) VALUES (?, ?)", (guild, user))
        (xp,) = conn.execute("SELECT xp FROM users WHERE guild=? AND user=?", (guild, user)).fetchone()
        new_xp = max(0, xp + amount)
        old, new = level_of(xp), level_of(new_xp)
        reward = sum(lv * level_points for lv in range(old + 1, new + 1))
        conn.execute("UPDATE users SET xp=?, points=points+? WHERE guild=? AND user=?",
                     (new_xp, reward, guild, user))
    return old, new, reward


def add_points(guild, user, amount):
    with conn:
        conn.execute("""INSERT INTO users(guild, user, points) VALUES (?, ?, MAX(0, ?))
                        ON CONFLICT(guild, user) DO UPDATE SET points = MAX(0, points + ?)""",
                     (guild, user, amount, amount))
    return get_user(guild, user)[1]


def transfer(guild, sender, receiver, amount):
    with conn:
        cur = conn.execute("UPDATE users SET points=points-? WHERE guild=? AND user=? AND points>=?",
                           (amount, guild, sender, amount))
        if cur.rowcount == 0:
            return False
        conn.execute("""INSERT INTO users(guild, user, points) VALUES (?, ?, ?)
                        ON CONFLICT(guild, user) DO UPDATE SET points = points + excluded.points""",
                     (guild, receiver, amount))
    return True


def rank(guild, user):
    xp = get_user(guild, user)[0]
    return conn.execute("SELECT COUNT(*) + 1 FROM users WHERE guild=? AND xp>?", (guild, xp)).fetchone()[0]


def member_count(guild):
    return conn.execute("SELECT COUNT(*) FROM users WHERE guild=? AND (xp>0 OR points>0)", (guild,)).fetchone()[0]


def leaderboard(guild, column, offset, limit):
    assert column in BOARD_COLUMNS
    return conn.execute(f"""SELECT user, xp, points FROM users WHERE guild=? AND (xp>0 OR points>0)
                            ORDER BY {column} DESC, user LIMIT ? OFFSET ?""", (guild, limit, offset)).fetchall()


def reset(guild, user=None):
    with conn:
        if user is None:
            conn.execute("DELETE FROM users WHERE guild=?", (guild,))
        else:
            conn.execute("DELETE FROM users WHERE guild=? AND user=?", (guild, user))


def get_settings(guild):
    conn.execute("INSERT OR IGNORE INTO settings(guild) VALUES (?)", (guild,))
    cur = conn.execute("SELECT * FROM settings WHERE guild=?", (guild,))
    return dict(zip([c[0] for c in cur.description], cur.fetchone()))


def update_settings(guild, **fields):
    assert fields.keys() <= SETTING_FIELDS
    get_settings(guild)
    with conn:
        conn.execute(f"UPDATE settings SET {', '.join(f'{k}=?' for k in fields)} WHERE guild=?",
                     (*fields.values(), guild))


def level_roles(guild):
    return conn.execute("SELECT level, role FROM level_roles WHERE guild=? ORDER BY level", (guild,)).fetchall()


def set_level_role(guild, level, role):
    with conn:
        if role is None:
            conn.execute("DELETE FROM level_roles WHERE guild=? AND level=?", (guild, level))
        else:
            conn.execute("INSERT OR REPLACE INTO level_roles VALUES (?, ?, ?)", (guild, level, role))


def toggle_no_xp(guild, target, kind):
    with conn:
        if conn.execute("DELETE FROM no_xp WHERE guild=? AND target=?", (guild, target)).rowcount:
            return False
        conn.execute("INSERT INTO no_xp VALUES (?, ?, ?)", (guild, target, kind))
    return True


def no_xp(guild):
    return conn.execute("SELECT target, kind FROM no_xp WHERE guild=?", (guild,)).fetchall()
