"""Create the private map trivia unlock ledger used by authenticated API routes."""

from sqlalchemy import inspect, text

from database import engine
from models import MapTriviaUnlock


LEGACY_STATIC_SPOTS = [
    {
        "legacy_spot_id": "tokyo_001",
        "title": "東京タワーの色の雑学",
        "content": "東京タワーの赤と白の塗り分けは、航空法で定められた昼間障害標識として目立たせるためのものです。現在の正式な色名はインターナショナルオレンジと白です。",
        "explanation": "高さのある建造物は航空機から見つけやすい配色が求められます。東京タワーの色は景観だけでなく、空の安全を守るための目印として機能しています。",
        "prefecture": "東京都", "address": "東京タワー", "latitude": 35.6586, "longitude": 139.7454, "radius": 300,
    },
    {
        "legacy_spot_id": "kyoto_001",
        "title": "伏見稲荷の鳥居の雑学",
        "content": "伏見稲荷大社の千本鳥居は、願いが通る、通ったという意味から奉納されてきました。鳥居の数は境内全体で数千基にのぼります。",
        "explanation": "鳥居は願いごとが成就した感謝や祈願のしるしとして奉納されてきました。参道に連なる朱色の鳥居は、長い信仰の積み重ねを目で見られる景色です。",
        "prefecture": "京都府", "address": "伏見稲荷大社", "latitude": 34.9671, "longitude": 135.7727, "radius": 350,
    },
    {
        "legacy_spot_id": "osaka_001",
        "title": "通天閣とビリケンさんの雑学",
        "content": "通天閣の展望台にいるビリケンさんは、足の裏をなでると幸運が訪れるといわれています。初代通天閣は1912年に建てられました。",
        "explanation": "ビリケン像はもともとアメリカ生まれの幸運の神様として広まりました。大阪では通天閣の名物として親しまれ、足の裏をなでる習慣が観光体験になっています。",
        "prefecture": "大阪府", "address": "通天閣", "latitude": 34.6525, "longitude": 135.5063, "radius": 300,
    },
    {
        "legacy_spot_id": "hokkaido_001",
        "title": "札幌時計台の雑学",
        "content": "札幌市時計台は、もともと札幌農学校の演武場として建てられました。現在も街の中心部で時を刻む、北海道開拓期を伝える建物です。",
        "explanation": "演武場は学生の兵式訓練や式典に使われた施設でした。時計台は単なる時計の建物ではなく、札幌農学校と北海道開拓の歴史を残す文化財です。",
        "prefecture": "北海道", "address": "札幌市時計台", "latitude": 43.0626, "longitude": 141.3537, "radius": 300,
    },
    {
        "legacy_spot_id": "okinawa_001",
        "title": "首里城の赤瓦の雑学",
        "content": "首里城の赤瓦は沖縄の強い日差しに映えるだけでなく、琉球王国時代の建築文化を象徴する意匠として知られています。",
        "explanation": "赤瓦は沖縄の土や気候、建築文化と結びついた素材です。首里城の色彩は中国や日本の影響を受けつつ、琉球独自の美意識を伝えています。",
        "prefecture": "沖縄県", "address": "首里城", "latitude": 26.2170, "longitude": 127.7194, "radius": 400,
    },
]


def migrate() -> None:
    map_columns = {
        column["name"] for column in inspect(engine).get_columns("map_trivia")
    }
    if "is_active" not in map_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE map_trivia "
                "ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE"
            ))
    if "legacy_spot_id" not in map_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE map_trivia ADD COLUMN legacy_spot_id VARCHAR"))
    if "legacy_trivia_id" not in map_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE map_trivia ADD COLUMN legacy_trivia_id INTEGER"))

    with engine.begin() as connection:
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_map_trivia_legacy_spot_id "
            "ON map_trivia (legacy_spot_id) WHERE legacy_spot_id IS NOT NULL"
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_map_trivia_legacy_trivia_id "
            "ON map_trivia (legacy_trivia_id) WHERE legacy_trivia_id IS NOT NULL"
        ))
        for spot in LEGACY_STATIC_SPOTS:
            connection.execute(text("""
                INSERT INTO map_trivia (
                    title, content, explanation, source, category,
                    map_address, map_prefecture, map_latitude, map_longitude,
                    map_radius, map_hint, is_active, legacy_spot_id
                )
                SELECT :title, :content, :explanation, '', '地域',
                       :address, :prefecture, :latitude, :longitude,
                       :radius, '', FALSE, :legacy_spot_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM map_trivia WHERE legacy_spot_id = :legacy_spot_id
                )
            """), spot)

        # Persist the old trivia_N -> map_N relation once, so later editorial
        # changes to title/content can never break a collector's alias again.
        connection.execute(text("""
            UPDATE map_trivia AS m
            SET legacy_trivia_id = matched.trivia_id
            FROM (
                SELECT MIN(t.id) AS trivia_id, t.title, t.content
                FROM trivia AS t
                JOIN map_trivia AS candidate
                  ON candidate.title = t.title AND candidate.content = t.content
                WHERE candidate.legacy_trivia_id IS NULL
                GROUP BY t.title, t.content
                HAVING COUNT(DISTINCT t.id) = 1
                   AND COUNT(DISTINCT candidate.id) = 1
            ) AS matched
            WHERE m.title = matched.title
              AND m.content = matched.content
              AND m.legacy_trivia_id IS NULL
        """))

    if "map_trivia_unlocks" not in inspect(engine).get_table_names():
        MapTriviaUnlock.__table__.create(engine)

    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as connection:
        # A map entry may be archived but must never cascade-delete a
        # collector's ledger. RESTRICT also catches accidental hard deletes.
        connection.execute(text("""
            DO $$
            DECLARE fk_name text;
                    delete_action "char";
            BEGIN
                SELECT conname, confdeltype INTO fk_name, delete_action
                FROM pg_constraint
                WHERE conrelid = 'map_trivia_unlocks'::regclass
                  AND contype = 'f'
                  AND pg_get_constraintdef(oid) LIKE '%map_trivia_id%';
                IF fk_name IS NULL OR delete_action <> 'r' THEN
                    IF fk_name IS NOT NULL THEN
                        EXECUTE format(
                            'ALTER TABLE map_trivia_unlocks DROP CONSTRAINT %I',
                            fk_name
                        );
                    END IF;
                    ALTER TABLE map_trivia_unlocks
                        ADD CONSTRAINT map_trivia_unlocks_map_trivia_id_fkey
                        FOREIGN KEY (map_trivia_id) REFERENCES map_trivia(id)
                        ON DELETE RESTRICT;
                END IF;
            END $$;
        """))

        app_user_exists = connection.execute(text(
            "SELECT 1 FROM pg_roles WHERE rolname = 'app_user'"
        )).scalar()
        # Some isolated staging databases use only the owner connection. The
        # table stays private there because no application role has a grant.
        if not app_user_exists:
            return

        connection.execute(text(
            "GRANT SELECT, INSERT ON map_trivia_unlocks TO app_user"
        ))
        connection.execute(text(
            "GRANT USAGE, SELECT ON SEQUENCE map_trivia_unlocks_id_seq TO app_user"
        ))
        connection.execute(text(
            "ALTER TABLE map_trivia_unlocks ENABLE ROW LEVEL SECURITY"
        ))
        connection.execute(text(
            "DROP POLICY IF EXISTS map_trivia_unlocks_select_own ON map_trivia_unlocks"
        ))
        connection.execute(text(
            "CREATE POLICY map_trivia_unlocks_select_own ON map_trivia_unlocks "
            "FOR SELECT TO app_user USING "
            "(user_id = current_setting('app.current_user_id', true))"
        ))
        connection.execute(text(
            "DROP POLICY IF EXISTS map_trivia_unlocks_insert_own ON map_trivia_unlocks"
        ))
        connection.execute(text(
            "CREATE POLICY map_trivia_unlocks_insert_own ON map_trivia_unlocks "
            "FOR INSERT TO app_user WITH CHECK "
            "(user_id = current_setting('app.current_user_id', true))"
        ))


if __name__ == "__main__":
    migrate()
