from types import SimpleNamespace

import bot
import db

db.open_db(":memory:")

assert [db.level_of(x) for x in (0, 99, 100, 254, 255, 475)] == [0, 0, 1, 1, 2, 3]
assert db.level_progress(300) == (2, 45, 220)

assert db.add_xp(1, 1, 99, 100) == (0, 0, 0)
assert db.add_xp(1, 1, 1, 100) == (0, 1, 100)
assert db.add_xp(1, 1, 375, 100) == (1, 3, 500)
assert db.get_user(1, 1) == (475, 600)
assert db.add_xp(1, 1, -10_000, 100) == (3, 0, 0)
assert db.get_user(1, 1) == (0, 600)

assert db.transfer(1, 1, 2, 601) is False
assert db.transfer(1, 1, 2, 600) is True
assert db.get_user(1, 1)[1] == 0 and db.get_user(1, 2)[1] == 600
assert db.add_points(1, 3, -50) == 0
assert db.add_points(1, 2, -100) == 500
assert db.add_points(1, 3, -1000) == 0

db.add_xp(1, 4, 500, 0)
db.add_xp(2, 9, 9999, 0)
assert db.rank(1, 4) == 1 and db.rank(1, 1) == 2
assert [r[0] for r in db.leaderboard(1, "xp", 0, 10)] == [4, 2]
assert [r[0] for r in db.leaderboard(1, "points", 0, 10)] == [2, 4]
assert db.member_count(1) == 2
db.reset(1, 4)
assert db.get_user(1, 4) == (0, 0) and db.get_user(2, 9)[0] == 9999

assert db.get_settings(1)["level_points"] == 100
db.update_settings(1, level_points=7, stack_roles=False)
assert db.get_settings(1)["level_points"] == 7 and db.get_settings(1)["stack_roles"] == 0

assert db.toggle_no_xp(1, 55, "channel") is True
assert db.toggle_no_xp(1, 55, "channel") is False
assert db.no_xp(1) == []

rewards = [(5, 50), (10, 100), (20, 200)]
assert bot.role_diff(rewards, 12, True, {999}) == ({50, 100}, set())
assert bot.role_diff(rewards, 12, False, {50, 999}) == ({100}, {50})
assert bot.role_diff(rewards, 3, True, {50, 100}) == (set(), {50, 100})

member = SimpleNamespace(mention="<@1>", display_name="멤버", guild=SimpleNamespace(name="서버"))
assert bot.render_message("{user} {name} {level} {points} {server} {0.__class__}", member, 3, 1500) \
    == "<@1> 멤버 3 1,500 서버 {0.__class__}"

assert bot.delta("set", 10, 30) == -20
print("ok")
