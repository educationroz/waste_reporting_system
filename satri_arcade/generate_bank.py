#!/usr/bin/env python3
"""
SATRI Arcade — Question Bank Generator
=======================================
Generates questions.json with 500+ questions for EVERY game section.

Games covered:
  - SQL Master      : 500+ auto-generated MCQs (correct-query picking)
  - Git Master      : 500+ MCQs (command tasks + concepts)
  - Word Scramble /
    Speed Typing    : 500+ tech words (shared wordPool)
  - Bug Hunter      : 500+ challenges PER FIELD (via shared language pools)
  - Color Flash / Memory Grid / Flash Recall : engine-generated (no bank needed)

Bug Hunter uses SHARED language pools (js, python, php, c, ...) mapped to fields,
so every challenge is stored ONCE in the JSON but every field still gets 500+.

Run:      python3 generate_bank.py
Output:   questions.json (+ pool count report)
Sources:  All questions are generated from templates written for this project
          (see README.md "Sources" section for details & external sources).
"""

import json
import random
from datetime import date

random.seed(20260822)

# ============================================================
# Helpers
# ============================================================

def mcq(obj, correct, w1, w2, w3):
    opts = [correct, w1, w2, w3]
    random.shuffle(opts)
    return {"objective": obj, "options": opts, "correctIndex": opts.index(correct)}


def bug(lines, bug_index, explanation, difficulty="medium"):
    return {"difficulty": difficulty, "lines": list(lines), "bugIndex": bug_index,
            "explanation": explanation}


def dedupe(items, keyfunc):
    seen, out = set(), []
    for it in items:
        k = keyfunc(it)
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


def build_mcq_pool(families, target, name):
    raw = []
    for fam in families:
        raw.extend(fam())
    raw = dedupe(raw, lambda q: q["objective"])
    random.shuffle(raw)
    print(f"  {name}: {len(raw)} unique MCQs (target {target})")
    assert len(raw) >= target, f"{name} pool short: {len(raw)} < {target}"
    return raw[:target]


def build_bug_pool(patterns, target, name):
    seen, out, guard = set(), [], 0
    while len(out) < target and guard < target * 400:
        guard += 1
        pat = random.choice(patterns)
        item = pat()
        if item is None:
            continue
        if not (0 <= item["bugIndex"] < len(item["lines"])):
            continue
        if not all(isinstance(l, str) and l.strip() for l in item["lines"]):
            continue
        k = tuple(item["lines"])
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    print(f"  {name}: {len(out)} unique challenges (target {target})")
    assert len(out) >= target, f"{name} pool short: {len(out)} < {target}"
    return out


# Param factories: statement templates + random id/value injection
IDS = ["user", "item", "total", "price", "count", "data", "result", "value",
       "score", "msg", "task", "stock", "name", "list", "rows", "temp",
       "flag", "rate", "token", "index", "level", "limit", "queue", "cache",
       "label", "entry", "node", "edge", "grid", "cell", "slot", "seed",
       "mode", "path", "base", "core", "unit", "pair", "step"]
VALS = [0, 1, 3, 5, 7, 10, 12, 15, 18, 20, 25, 30, 36, 42, 50, 64, 75, 99,
        100, 128, 250, 300, 500, 640, 750, 999, 1000, 1500, 2500, 5000]


def idv():
    return random.choice(IDS), random.choice(VALS)


def fmt_list(fmts, note, diff="easy", follow_default=""):
    """Missing-colon/semicolon style table: list of (stmt, follow) templates."""
    pats = []
    for stmt, follow in fmts:
        def gen(s=stmt, f=follow):
            a, v = idv()
            lines = [s.format(a=a, v=v), f.format(a=a, v=v)]
            return bug(lines, 0, note, diff)
        pats.append(gen)
    return pats


# ============================================================
# 1) SQL MASTER — 500+ MCQs
# ============================================================

TBLS = [
    # table, rows-word, num col, text col, text values, group col
    ("products", "products", "price", "category", ["Electronics", "Books", "Toys"], "brand"),
    ("employees", "employees", "salary", "department", ["Sales", "HR", "Engineering"], "department"),
    ("orders", "orders", "total", "status", ["pending", "shipped", "cancelled"], "customer_id"),
    ("users", "users", "age", "city", ["Kathmandu", "Pokhara", "Lalitpur"], "country"),
    ("students", "students", "marks", "faculty", ["Science", "Management", "Arts"], "faculty"),
    ("movies", "movies", "rating", "genre", ["Action", "Comedy", "Drama"], "language"),
    ("invoices", "invoices", "amount", "status", ["paid", "unpaid", "overdue"], "region"),
    ("books", "books", "pages", "genre", ["Fiction", "History", "Science"], "author"),
]
THRESH = [100, 500, 1000, 5000, 50000]
JOINS = [
    ("customers", "orders", "customers.id", "orders.customer_id", "customers.name", "orders.total"),
    ("users", "orders", "users.id", "orders.user_id", "users.name", "orders.total"),
    ("students", "enrollments", "students.id", "enrollments.student_id", "students.name", "enrollments.grade"),
    ("authors", "books", "authors.id", "books.author_id", "authors.name", "books.title"),
]


def sql_where_num():
    out = []
    for t, rows, col, tc, tv, g in TBLS:
        for v in THRESH:
            for sym, word in [(">", "greater than"), ("<", "less than"), (">=", "at least"), ("<=", "at most")]:
                out.append(mcq(
                    f"Fetch all {rows} from the '{t}' table where {col} is {word} {v}.",
                    f"SELECT * FROM {t} WHERE {col} {sym} {v};",
                    f"SELECT * FROM {t} HAVING {col} {sym} {v};",
                    f"SELECT * FROM {t} WHERE {col} => {v};",
                    f"QUERY {t} FILTER {col} {sym} {v};"))
    return out


def sql_where_text():
    out = []
    for t, rows, col, tc, tv, g in TBLS:
        for val in tv:
            out.append(mcq(
                f"Get all {rows} whose {tc} is exactly '{val}'.",
                f"SELECT * FROM {t} WHERE {tc} = '{val}';",
                f"SELECT * FROM {t} WHERE {tc} == '{val}';",
                f"SELECT * FROM {t} WHERE {tc} = {val};",
                f"SELECT * FROM {t} MATCHES {tc} = '{val}';"))
    return out


def sql_order():
    out = []
    for t, rows, col, tc, tv, g in TBLS:
        for c, cname in [(col, col), (tc, tc), (g, g)]:
            for d, dw in [("ASC", "ascending"), ("DESC", "descending")]:
                out.append(mcq(
                    f"List all {rows} from '{t}' sorted by {cname} in {dw} order.",
                    f"SELECT * FROM {t} ORDER BY {cname} {d};",
                    f"SELECT * FROM {t} SORT BY {cname} {d};",
                    f"SELECT * FROM {t} ORDER {cname} {d};",
                    f"SELECT * FROM {t} ARRANGE BY {cname} {d};"))
    return out


def sql_topn():
    out = []
    for t, rows, col, tc, tv, g in TBLS:
        for n in [3, 5, 10]:
            for d in ["ASC", "DESC"]:
                out.append(mcq(
                    f"Get the top {n} {rows} from '{t}' with the {'lowest' if d == 'ASC' else 'highest'} {col}.",
                    f"SELECT * FROM {t} ORDER BY {col} {d} LIMIT {n};",
                    f"SELECT * FROM {t} LIMIT {n} ORDER BY {col} {d};",
                    f"SELECT * FROM {t} ORDER BY {col} {d} ROWS {n};",
                    f"SELECT * FROM {t} ORDER BY {col} {d} FIRST {n};"))
    return out


def sql_count_agg():
    out = []
    for t, rows, col, tc, tv, g in TBLS:
        out.append(mcq(f"Count the total number of {rows} in the '{t}' table.",
                       f"SELECT COUNT(*) FROM {t};",
                       f"SELECT TOTAL(*) FROM {t};",
                       f"SELECT COUNT({t}) FROM {t};",
                       f"SELECT SUM(*) FROM {t};"))
        for fn, word, wrong in [("AVG", "average", "MEAN"), ("MAX", "maximum", "BIGGEST"),
                                ("MIN", "minimum", "SMALLEST"), ("SUM", "total", "PLUS")]:
            out.append(mcq(f"Find the {word} {col} across all {rows} in '{t}'.",
                           f"SELECT {fn}({col}) FROM {t};",
                           f"SELECT {wrong}({col}) FROM {t};",
                           f"SELECT {fn}({t}) FROM {t};",
                           f"SELECT {fn}(*) FROM {t} WHERE {col};"))
    return out


def sql_group_having():
    out = []
    for t, rows, col, tc, tv, g in TBLS:
        for fn, word in [("SUM", "total"), ("AVG", "average")]:
            out.append(mcq(f"Show the {word} {col} for each {g} in '{t}'.",
                           f"SELECT {g}, {fn}({col}) FROM {t} GROUP BY {g};",
                           f"SELECT {g}, {fn}({col}) FROM {t} GROUP {g};",
                           f"SELECT {g}, {fn}({col}) FROM {t} SUM BY {g};",
                           f"SELECT {g}, {fn}({col}) FROM {t} ORDER BY {g};"))
        for n in [3, 5, 10]:
            out.append(mcq(f"Show only those {g} groups in '{t}' that contain more than {n} {rows}.",
                           f"SELECT {g} FROM {t} GROUP BY {g} HAVING COUNT(*) > {n};",
                           f"SELECT {g} FROM {t} WHERE COUNT(*) > {n} GROUP BY {g};",
                           f"SELECT {g} FROM {t} GROUP BY {g} ORDER BY COUNT(*) > {n};",
                           f"SELECT {g} FROM {t} HAVING COUNT(*) > {n};"))
    return out


def sql_distinct_like():
    out = []
    for t, rows, col, tc, tv, g in TBLS:
        val = tv[0]
        for c in [tc, g]:
            out.append(mcq(f"Retrieve unique {c} values from the '{t}' table (no duplicates).",
                           f"SELECT DISTINCT {c} FROM {t};",
                           f"SELECT DISTINCT(*) {c} FROM {t};",
                           f"SELECT ONLY {c} FROM {t};",
                           f"SELECT NODUP {c} FROM {t};"))
        out.append(mcq(f"Find {rows} in '{t}' whose {tc} starts with '{val[0]}'.",
                       f"SELECT * FROM {t} WHERE {tc} LIKE '{val[0]}%';",
                       f"SELECT * FROM {t} WHERE {tc} LIKE '%{val[0]}';",
                       f"SELECT * FROM {t} WHERE {tc} STARTS '{val[0]}';",
                       f"SELECT * FROM {t} WHERE {tc} LIKE '{val[0]}*';"))
        out.append(mcq(f"Find {rows} in '{t}' whose {tc} ends with 'e'.",
                       f"SELECT * FROM {t} WHERE {tc} LIKE '%e';",
                       f"SELECT * FROM {t} WHERE {tc} LIKE 'e%';",
                       f"SELECT * FROM {t} WHERE {tc} ENDS 'e';",
                       f"SELECT * FROM {t} WHERE {tc} LIKE '%e%';"))
        out.append(mcq(f"Find {rows} in '{t}' whose {tc} contains 'a' anywhere.",
                       f"SELECT * FROM {t} WHERE {tc} LIKE '%a%';",
                       f"SELECT * FROM {t} WHERE {tc} LIKE 'a%';",
                       f"SELECT * FROM {t} WHERE {tc} CONTAINS 'a';",
                       f"SELECT * FROM {t} WHERE {tc} LIKE '_a_';"))
    return out


def sql_between_in_null():
    out = []
    for t, rows, col, tc, tv, g in TBLS:
        lo, hi = 100, 1000
        out.append(mcq(f"Fetch {rows} from '{t}' where {col} is between {lo} and {hi} (inclusive).",
                       f"SELECT * FROM {t} WHERE {col} BETWEEN {lo} AND {hi};",
                       f"SELECT * FROM {t} WHERE {col} FROM {lo} TO {hi};",
                       f"SELECT * FROM {t} WHERE {col} RANGE {lo} - {hi};",
                       f"SELECT * FROM {t} WHERE {col} IN ({lo}, {hi});"))
        out.append(mcq(f"Select {rows} from '{t}' whose {g} is one of: X, Y, Z.",
                       f"SELECT * FROM {t} WHERE {g} IN ('X', 'Y', 'Z');",
                       f"SELECT * FROM {t} WHERE {g} = 'X' OR 'Y' OR 'Z';",
                       f"SELECT * FROM {t} WHERE {g} BETWEEN 'X' AND 'Z';",
                       f"SELECT * FROM {t} WHERE {g} LIKE ('X', 'Y', 'Z');"))
        out.append(mcq(f"Find {rows} in '{t}' where {tc} has no value (missing data).",
                       f"SELECT * FROM {t} WHERE {tc} IS NULL;",
                       f"SELECT * FROM {t} WHERE {tc} = NULL;",
                       f"SELECT * FROM {t} WHERE {tc} == NULL;",
                       f"SELECT * FROM {t} WHERE {tc} IS EMPTY;"))
        out.append(mcq(f"Show {tc} for {rows} in '{t}', but print 'N/A' when it is NULL.",
                       f"SELECT COALESCE({tc}, 'N/A') FROM {t};",
                       f"SELECT NULLIF({tc}, 'N/A') FROM {t};",
                       f"SELECT ISNULL({tc}, 'N/A') OR NULL FROM {t};",
                       f"SELECT REPLACE({tc}, NULL, 'N/A') FROM {t};"))
    return out


def sql_dml():
    out = []
    for t, rows, col, tc, tv, g in TBLS:
        val = tv[0]
        out.append(mcq(f"Insert a new row into '{t}' with {tc}='{val}' and {col}=100.",
                       f"INSERT INTO {t} ({tc}, {col}) VALUES ('{val}', 100);",
                       f"INSERT INTO {t} SET {tc}='{val}', {col}=100;",
                       f"ADD INTO {t} ({tc}, {col}) VALUES ('{val}', 100);",
                       f"INSERT VALUES ('{val}', 100) INTO {t};"))
        out.append(mcq(f"Set {col} to 100 for the {t[:-1]} with id 7.",
                       f"UPDATE {t} SET {col} = 100 WHERE id = 7;",
                       f"MODIFY {t} SET {col} = 100 WHERE id = 7;",
                       f"UPDATE {t} SET {col} = 100;",
                       f"UPDATE SET {col} = 100 IN {t} WHERE id = 7;"))
        out.append(mcq(f"Remove {rows} from '{t}' where {tc} is '{val}'.",
                       f"DELETE FROM {t} WHERE {tc} = '{val}';",
                       f"REMOVE FROM {t} WHERE {tc} = '{val}';",
                       f"DELETE * FROM {t} WHERE {tc} = '{val}';",
                       f"DROP FROM {t} WHERE {tc} = '{val}';"))
        out.append(mcq(f"Empty the '{t}' table quickly but KEEP its structure and columns.",
                       f"TRUNCATE TABLE {t};",
                       f"DROP TABLE {t};",
                       f"DELETE TABLE {t};",
                       f"CLEAR TABLE {t};"))
    return out


def sql_joins():
    out = []
    for t1, t2, k1, k2, n1, n2 in JOINS:
        out.append(mcq(f"List each {n1.split('.')[0]} name together with their {n2.split('.')[1]} "
                       f"(only matching rows) from '{t1}' and '{t2}'.",
                       f"SELECT {n1}, {n2} FROM {t1} INNER JOIN {t2} ON {k1} = {k2};",
                       f"SELECT {n1}, {n2} FROM {t1} JOIN WITH {t2} ON {k1} = {k2};",
                       f"SELECT {n1}, {n2} FROM {t1} INNER JOIN {t2} WHERE {k1} = {k2};",
                       f"SELECT {n1}, {n2} FROM {t1} LINK {t2} ON id;"))
        out.append(mcq(f"Find {t1} that have NO matching row in '{t2}'.",
                       f"SELECT {n1} FROM {t1} LEFT JOIN {t2} ON {k1} = {k2} WHERE {k2} IS NULL;",
                       f"SELECT {n1} FROM {t1} LEFT JOIN {t2} ON {k1} = {k2} WHERE {k2} = NULL;",
                       f"SELECT {n1} FROM {t1} EXCEPT JOIN {t2};",
                       f"SELECT {n1} FROM {t1} MISSING JOIN {t2};"))
    return out


def sql_misc():
    out = []
    for t, rows, col, tc, tv, g in TBLS:
        out.append(mcq(f"Show {col} for {rows} in '{t}' with a column alias named 'amount'.",
                       f"SELECT {col} AS amount FROM {t};",
                       f"SELECT {col} RENAMED amount FROM {t};",
                       f"SELECT {col} -> amount FROM {t};",
                       f"SELECT amount = {col} FROM {t};"))
        out.append(mcq(f"Label each {t[:-1]} in '{t}': 'high' when {col} > 1000, else 'low'.",
                       f"SELECT *, CASE WHEN {col} > 1000 THEN 'high' ELSE 'low' END AS label FROM {t};",
                       f"SELECT *, IF {col} > 1000 THEN 'high' ELSE 'low' FROM {t};",
                       f"SELECT *, SWITCH({col} > 1000, 'high', 'low') FROM {t};",
                       f"SELECT *, {col} > 1000 ? 'high' : 'low' FROM {t};"))
        out.append(mcq(f"Get the second highest {col} from '{t}'.",
                       f"SELECT MAX({col}) FROM {t} WHERE {col} < (SELECT MAX({col}) FROM {t});",
                       f"SELECT SECOND_MAX({col}) FROM {t};",
                       f"SELECT MAX({col}, 2) FROM {t};",
                       f"SELECT TOP 2 {col} FROM {t} OFFSET 2;"))
        out.append(mcq(f"Show the average {col} in '{t}' rounded to 2 decimal places.",
                       f"SELECT ROUND(AVG({col}), 2) FROM {t};",
                       f"SELECT AVG(ROUND({col}, 2)) FROM {t};",
                       f"SELECT ROUND(AVG({col})), 2 FROM {t};",
                       f"SELECT AVG({col}, 2) FROM {t};"))
    for t1, t2, k1, k2, n1, n2 in JOINS[:2]:
        out.append(mcq(f"Combine names from '{t1}' and '{t2}' into one list, removing duplicates.",
                       f"SELECT name FROM {t1} UNION SELECT name FROM {t2};",
                       f"SELECT name FROM {t1} MERGE SELECT name FROM {t2};",
                       f"SELECT name FROM {t1} + SELECT name FROM {t2};",
                       f"JOIN SELECT name FROM {t1}, {t2};"))
    out.append(mcq("Create table 'courses' with id (int, primary key) and title (text).",
                   "CREATE TABLE courses (id INT PRIMARY KEY, title TEXT);",
                   "NEW TABLE courses (id INT KEY, title TEXT);",
                   "CREATE courses TABLE (id INT PRIMARY, title TEXT);",
                   "TABLE CREATE courses (id INT PK ONLY, title TEXT);"))
    out.append(mcq("Add a nullable column 'phone' (varchar) to the 'users' table.",
                   "ALTER TABLE users ADD COLUMN phone VARCHAR(20);",
                   "UPDATE users ADD phone VARCHAR(20);",
                   "INSERT COLUMN phone VARCHAR(20) INTO users;",
                   "ALTER users ATTACH phone VARCHAR(20);"))
    out.append(mcq("Rename column 'uname' to 'username' in the 'users' table.",
                   "ALTER TABLE users RENAME COLUMN uname TO username;",
                   "UPDATE users RENAME uname TO username;",
                   "ALTER TABLE users SET COLUMN uname = username;",
                   "RENAME TABLE users COLUMN uname TO username;"))
    out.append(mcq("Remove the column 'age' from the 'students' table.",
                   "ALTER TABLE students DROP COLUMN age;",
                   "DELETE COLUMN age FROM students;",
                   "ALTER students REMOVE age;",
                   "UPDATE students DROP age;"))
    return out


# ============================================================
# 2) GIT MASTER — 500+ MCQs
# ============================================================

BRANCHES = ["feature-login", "develop", "hotfix-payment", "feature-search", "release-2.0",
            "bugfix-header", "experiment-ui", "feature-darkmode", "feature-checkout",
            "hotfix-crash", "release-1.5", "feature-profile", "bugfix-typo", "develop-api",
            "feature-reports", "hotfix-security", "experiment-api", "feature-notifications"]
FILES = ["style.css", "app.js", "index.html", "config.env", "README.md", "server.py",
         "utils.js", "main.py", "data.json", "logo.png", "test.js", "api.php"]
MSGS = ["fix bug", "add login page", "update docs", "refactor api", "fix typo",
        "improve performance", "add tests", "update dependencies"]
TAGS = ["v1.0.0", "v1.2.0", "v2.0.0", "v2.3.1", "v3.0.0", "v0.9.0", "v1.5.2", "v2.10.0"]
HASHES = ["abc1234", "deadbee", "cafe123", "f00d42a", "998a77b"]


def git_branch_tasks():
    out = []
    for b in BRANCHES:
        out.append(mcq(f"Create a new branch called '{b}' WITHOUT switching to it.",
                       f"git branch {b}", f"git checkout {b}", f"git new-branch {b}", f"git branch --make {b}"))
        out.append(mcq(f"Create AND immediately switch to a new branch called '{b}'.",
                       f"git checkout -b {b}", f"git branch {b}", f"git switch-only {b}", f"git checkout {b} --new"))
        out.append(mcq(f"Switch to the existing branch '{b}' using the modern command.",
                       f"git switch {b}", f"git change {b}", f"git move {b}", f"git goto {b}"))
        out.append(mcq(f"Delete the local branch '{b}' (already fully merged).",
                       f"git branch -d {b}", f"git delete {b}", f"git remove branch {b}", f"git branch --erase {b}"))
    return out


def git_remote_tasks():
    out = []
    for b in BRANCHES[:8]:
        out.append(mcq(f"Push the local branch '{b}' to 'origin' for the first time, setting its upstream.",
                       f"git push -u origin {b}", f"git push origin --track {b}", f"git upload origin {b}",
                       f"git push --set origin {b}"))
        out.append(mcq(f"Merge the branch '{b}' into your current branch.",
                       f"git merge {b}", f"git combine {b}", f"git pull {b} --merge", f"git branch merge {b}"))
    for m in MSGS:
        out.append(mcq(f'Commit your staged changes with the message "{m}".',
                       f'git commit -m "{m}"', f'git commit "{m}"', f'git save -m "{m}"', f'git push -m "{m}"'))
    out.append(mcq("Download new commits from 'origin' WITHOUT merging them.",
                   "git fetch", "git pull --no-merge", "git download", "git sync"))
    out.append(mcq("Download from 'origin' AND merge into your current branch in one command.",
                   "git pull", "git fetch --merge-now", "git get", "git remote merge"))
    out.append(mcq("List every remote repository with its URL.",
                   "git remote -v", "git remotes", "git origin list", "git show remotes"))
    out.append(mcq("Connect a NEW remote named 'origin' to a repo URL.",
                   "git remote add origin <url>", "git origin add <url>", "git connect origin <url>",
                   "git remote set origin <url>"))
    out.append(mcq("Clone a remote repository onto your machine.",
                   "git clone <url>", "git copy <url>", "git fetch --new <url>", "git pull --init <url>"))
    out.append(mcq("Initialize a brand-new Git repository in the current folder.",
                   "git init", "git start", "git new repo", "git create"))
    out.append(mcq("Safely push rewritten history, refusing if others pushed new commits.",
                   "git push --force-with-lease", "git push --force", "git push --safe", "git push --overwrite"))
    return out


def git_stage_file_tasks():
    out = []
    for f in FILES:
        out.append(mcq(f"Stage ONLY the file '{f}' for the next commit.",
                       f"git add {f}", f"git stage --only {f}", f"git commit {f}", f"git track {f}"))
        out.append(mcq(f"Discard uncommitted changes in just '{f}' (modern command).",
                       f"git restore {f}", f"git revert {f}", f"git discard {f}", f"git clean {f}"))
        out.append(mcq(f"Stop tracking '{f}' in Git but keep the file on disk.",
                       f"git rm --cached {f}", f"git delete --keep {f}", f"git ignore {f}", f"git untrack {f}"))
        out.append(mcq(f"Find which commit last changed lines of '{f}'.",
                       f"git blame {f}", f"git author {f}", f"git trace {f}", f"git history-line {f}"))
    out.append(mcq("Stage ALL new and modified files in the whole project.",
                   "git add .", "git commit -a --stage", "git stage all", "git add --everything-now"))
    out.append(mcq("Unstage everything that was added with git add (keep file contents).",
                   "git restore --staged .", "git undo add", "git reset --hard", "git unstage --all"))
    return out


def git_history_tasks():
    out = []
    for f in FILES[:6]:
        out.append(mcq(f"See the exact unstaged changes in the file '{f}'.",
                       f"git diff {f}", f"git changes {f}", f"git compare {f}", f"git log --file {f}"))
    out += [
        mcq("View commit history with one compact line per commit.",
            "git log --oneline", "git history --short", "git log -compact", "git show --brief"),
        mcq("View history of ALL branches drawn as an ASCII graph.",
            "git log --oneline --graph --all", "git tree --all", "git history --graph", "git log --map"),
        mcq("See the changes you staged for the next commit.",
            "git diff --staged", "git diff --remote", "git changes --staged", "git show staged"),
        mcq("Check which files are staged, unstaged or untracked.",
            "git status", "git check", "git diff --all", "git files"),
        mcq("See line-by-line changes since the last commit (working directory).",
            "git diff", "git changes", "git compare", "git log --diff"),
        mcq("Show full details (diff included) of the most recent commit.",
            "git show HEAD", "git display HEAD", "git open HEAD", "git log -1 --full"),
        mcq("Compare today's branch with how it looked 3 commits ago.",
            "git diff HEAD~3", "git diff --3", "git compare HEAD-3", "git old HEAD~3"),
    ]
    return out


def git_undo_tasks():
    out = []
    for m in ["fix login", "wip", "update readme", "temp save"]:
        out.append(mcq(f'You committed "{m}" with a wrong message. Fix ONLY the message of that last commit.',
                       'git commit --amend -m "new message"', 'git commit --change -m "new message"',
                       'git message -m "new message"', 'git edit HEAD -m "new message"'))
    out += [
        mcq("Undo the last commit but KEEP all its changes in the working directory.",
            "git reset --soft HEAD~1", "git revert --hard HEAD", "git undo last-commit", "git checkout HEAD~1 --discard"),
        mcq("Undo the last commit AND permanently delete its changes.",
            "git reset --hard HEAD~1", "git reset --soft HEAD~1", "git undo --keep HEAD~1", "git drop HEAD"),
        mcq("Create a NEW commit that reverses an old commit (safe for shared branches).",
            "git revert <hash>", "git reset <hash>", "git invert <hash>", "git undo <hash>"),
        mcq("You ran a hard reset and lost a commit. What shows the missing commits so you can recover them?",
            "git reflog", "git recover", "git undo reset", "git log --deleted"),
        mcq("Automatically binary-search history to find the commit that introduced a bug.",
            "git bisect start", "git search --bug", "git binary find", "git log --find-bug"),
        mcq("Temporarily shelve uncommitted changes so you can switch branches.",
            "git stash", "git save", "git pause", "git hold"),
        mcq("Bring back the changes you shelved with the most recent stash.",
            "git stash pop", "git stash back", "git unstash --last", "git apply stash new"),
        mcq("List everything currently shelved in stash.",
            "git stash list", "git stash show-all", "git list stashes", "git stash --ls"),
        mcq("Copy a single commit from another branch onto your current branch.",
            "git cherry-pick <hash>", "git commit copy <hash>", "git pick <hash>", "git graft <hash>"),
        mcq("Replay your current branch's commits on top of the latest 'main'.",
            "git rebase main", "git replay main", "git refresh main", "git merge main --top"),
    ]
    return out


def git_misc_tasks():
    out = []
    for tag in TAGS:
        out.append(mcq(f"Tag the current commit as release {tag}.",
                       f"git tag {tag}", f"git version {tag}", f"git mark {tag}", f"git release {tag}"))
    for h in HASHES:
        out.append(mcq(f"Apply the commit {h} from another branch onto your current branch.",
                       f"git cherry-pick {h}", f"git apply {h}", f"git copy-commit {h}", f"git merge {h} one"))
    out += [
        mcq("Set your global Git username to 'Ram Bahadur'.",
            'git config --global user.name "Ram Bahadur"', 'git config user.name --set "Ram Bahadur"',
            'git set user "Ram Bahadur"', 'git profile --name "Ram Bahadur"'),
        mcq("Set your global Git email for commits.",
            'git config --global user.email "ram@example.com"', 'git config --email "ram@example.com"',
            'git account set email "ram@example.com"', 'git email --global "ram@example.com"'),
        mcq("Which file tells Git which files/folders to never track?",
            ".gitignore", "ignore.git", ".gitconfig", "git.ignore"),
        mcq("What is a 'detached HEAD' state?",
            "You checked out a commit directly instead of a branch, so new commits belong to no branch",
            "The HEAD file inside .git got corrupted", "You deleted the .git folder by mistake",
            "Your branch has no commits yet"),
        mcq("On GitHub, what do you open to propose merging your branch into another?",
            "Pull Request", "Merge Ticket", "Push Request", "Branch Proposal"),
        mcq("What does 'origin' usually refer to?",
            "The default name of the remote repository you cloned from", "The first commit ever made",
            "Your Git installation folder", "The branch you are currently on"),
        mcq("What is the staging area (index)?",
            "A layer where changes are prepared before being committed",
            "The cloud backup of your repository", "The recycle bin for deleted branches",
            "The folder where Git stores its config"),
        mcq("Which merge creates NO merge commit and simply moves the branch pointer?",
            "Fast-forward merge", "Squash merge", "Octopus merge", "Revert merge"),
        mcq("What do conflict markers look like inside a file?",
            "<<<<<<< HEAD ... ======= ... >>>>>>> branch", "!!! START ... !!! END",
            "(( conflict )) ... (( yours ))", "## yours ## ... ## theirs ##"),
        mcq("Difference between git fetch and git pull?",
            "fetch downloads but does not merge; pull downloads AND merges",
            "fetch is for tags only; pull is for branches",
            "pull is read-only; fetch writes to history",
            "They are two names for the same command"),
        mcq("What does 'git clone' do that 'git pull' does not?",
            "Creates a full local copy of a remote repo you don't have yet",
            "Uploads your commits", "Deletes remote branches", "Merges two local branches"),
        mcq("Which command shows which branch you are currently on?",
            "git branch (current one marked with *)", "git where", "git current", "git branch --show-me"),
        mcq("List ALL branches including remote ones.",
            "git branch -a", "git branch --every", "git branches all", "git remote branches"),
        mcq("Rename your current local branch to 'main'.",
            "git branch -m main", "git branch rename main", "git rename main", "git branch --to main"),
        mcq("Remove stale references to remote branches that were deleted on the server.",
            "git remote prune origin", "git remote clean", "git branch vacuum", "git fetch --purge-all"),
        mcq("Abort a merge that produced conflicts, returning to the pre-merge state.",
            "git merge --abort", "git merge --cancel", "git undo merge", "git reset merge off"),
        mcq("Continue a rebase after fixing conflicts.",
            "git rebase --continue", "git rebase --next", "git rebase go", "git continue"),
        mcq("Create an annotated tag 'v1.0.0' with a message.",
            'git tag -a v1.0.0 -m "first release"', 'git tag v1.0.0 --note "first release"',
            'git tag --annotated v1.0.0 "first release"', 'git release -a v1.0.0'),
        mcq("Push your tags to the remote.",
            "git push --tags", "git push origin tags --all", "git tag push", "git upload tags"),
        mcq("Delete the remote branch 'old-feature' on origin.",
            "git push origin --delete old-feature", "git branch --remote-delete old-feature",
            "git remote remove old-feature", "git delete origin old-feature"),
        mcq("Which one is a syntax error?",
            "git push origin main extra-toomuch", "git push origin main", "git push", "git push origin"),
        mcq("Show a compact summary of who wrote the code in the repo.",
            "git shortlog -s", "git authors", "git count commits", "git log --writers"),
        mcq("Interactively choose which changed hunks to stage.",
            "git add -p", "git stage --pick", "git add --interactive-only", "git commit -p --stage"),
        mcq("Temporarily switch back to the branch you were on before the last checkout.",
            "git checkout -", "git switch back", "git checkout previous", "git switch last"),
        mcq("Save a stash with a readable description.",
            'git stash push -m "wip login"', 'git stash save name "wip login"',
            'git stash --label "wip login"', 'git hold -m "wip login"'),
        mcq("See which commits are on your branch but NOT yet on origin/main.",
            "git log origin/main..HEAD", "git diff origin main", "git log --not-pushed", "git unpushed"),
        mcq("Fetch changes from ALL configured remotes.",
            "git fetch --all", "git fetch *", "git pull --everything", "git remote update all-now"),
        mcq("Which file stores repo-level Git settings (in the .git folder)?",
            "config", "settings.ini", "git.cfg", "repo.conf"),
        mcq("Set VS Code as your default Git commit editor.",
            "git config --global core.editor \"code --wait\"", "git config editor vscode",
            "git set editor code", "git config --global editor.code true"),
        mcq("Which command creates the short hash shown beside each commit in git log --oneline?",
            "git log --oneline --abbrev-commit", "git log --tiny", "git hash short", "git log -s"),
        mcq("What does 'git blame' show for a file?",
            "Which commit and author last changed each line", "Who broke the build",
            "All branches containing the file", "File permission history"),
        mcq("Which is the safest order when publishing new work?",
            "commit -> pull --rebase -> push", "push -> commit -> pull", "pull --force -> push",
            "commit -> push --force -> pull"),
        mcq("What is a fork on GitHub?",
            "Your own remote copy of someone else's repository", "A split inside one branch",
            "A deleted commit", "A read-only tag"),
        mcq("After forking and cloning, which remote typically points at the ORIGINAL repo?",
            "upstream", "origin-true", "master", "base"),
        mcq("What does HEAD point to?",
            "The commit you currently have checked out", "The largest commit",
            "The first commit ever", "The remote server"),
        mcq("Which command safely updates your fork's main from the original repo (remote 'upstream')?",
            "git fetch upstream && git merge upstream/main", "git pull origin fork",
            "git sync fork", "git upstream merge now"),
        mcq("Which statement about .gitignore is TRUE?",
            "It only affects untracked files; already-tracked files keep being tracked",
            "It deletes files from your disk", "It also ignores files on GitHub releases",
            "It works only after the first commit"),
        mcq("What does 'git cherry' do?",
            "Shows commits in a branch that are not in another (upstream)", "Picks commits like cherry-pick",
            "Lists stashes", "Creates tags"),
        mcq("Reset staged AND working directory to match the last commit — dangerous but complete:",
            "git reset --hard", "git reset --soft", "git restore --staged", "git checkout --keep"),
        mcq("Which command rewrites the LAST 3 commits into one?",
            "git rebase -i HEAD~3 (squash)", "git merge --squash-last 3", "git commit --combine 3",
            "git fold HEAD~3"),
        mcq("How do you see just the names of changed files in a commit?",
            "git show --stat <hash>", "git show --files-only", "git diff --names <hash>", "git log --files"),
        mcq("What creates a brand-new local repo AND connects it to a remote in one flow?",
            "git init, then git remote add origin <url>", "git create --remote <url>",
            "git init <url>", "git clone --empty <url>"),
    ]
    return out


# ============================================================
# 3) WORD POOL — 500+ tech words (Speed Typing + Word Scramble)
# ============================================================

WORDS = """
java kotlin swift ruby golang rust linux unix docker kubernetes nginx apache redis mongo
mysql postgres sqlite mariadb graphql websocket restful microservice monolith serverless
lambda function macro thread coroutine mutex semaphore deadlock race stack heap pointer
recursion iteration regex parser lexer compiler interpreter transpiler runtime kernel shell
bash zsh powershell terminal console pipeline deployment rollback release artifact package
library module namespace import export bundle webpack vite rollup eslint prettier jest karma
mocha pytest junit selenium cypress playwright puppeteer coverage mutation fuzz stub mock
fixture spy assert breakpoint watch profiler heapdump trace latency throughput bandwidth
packet router switch subnet firewall proxy gateway tunnel protocol http https ftp smtp imap
dns dhcp nat ssh tls ssl certificate cipher hashing bcrypt salt pepper oauth jwt token
session cookie cache shard replica cluster queue broker kafka rabbitmq pubsub topic stream
batch delta snapshot backup archive schema table column row tuple index cursor trigger view
procedure transaction isolation deadlock rollback commit join nested aggregate filter mapper
reducer splice slice promise async await closure prototype delegate generic reflect sandbox
virtual daemon cron socket packet tracer firmware bootloader driver kernel sensor relay
actuator servo motor voltage circuit resistor capacitor diode transistor breadboard solder
multimeter signal frequency antenna bluetooth zigbee mesh lorawan mqtt canbus modbus plc
scada hmi telemetry gateway edgefog cluster swarm helm terraform ansible chef puppet jenkins
groovy circleci travis bamboo argoflux harbor prometheus grafana loki kibana elastic splunk
datadog newrelic sentry zabbix nagios ansible vault consul etcd raft paxos gossip quorum
leader election shard bitmap btree lsm wal mvcc acid base crud orm dto dao mvc mvvm clean
hexagonal solid dry kiss yagni taco agile scrum kanban sprint backlog retro storypoint
burndown gantt pivot roadmap stakeholder persona wireframe mockup prototype figma sketch
invision framer blender raster vector bezier kerning palette gradient shadow border radius
grid flexbox anim easing sprite atlas tilemap collider physics gravity raycast navmesh
pathfinding astar minimap leaderboard achievement quest inventory crafting dialogue cutscene
shader vertex fragment texture material lighting ambient specular diffuse bloom vignette
chromatic antialias dithering polygon mesh bone skinning rigging keyframe tween particles
emitter collider trigger respawn checkpoint savegame config autosave patch hotfix changelog
changelog versioning semantic prerelease nightly beta alpha canary stable featureflag toggle
experiment cohort funnel retention churn conversion attribution referral banner interstitial
newsletter subscriber funnel landing keyword backlink SERP crawl robots sitemap canonical
redirect slug meta viewport favicon thumbnail sprite glyph ligature emoji icon favicon
keyboard mouse gesture touch scroll swipe drag drop hover focus outline ripple snackbar toast
drawer sheet stepper carousel accordion chips fab appbar scaffold provider hook effect state
props render build deploy migrate seed fixture factory strategy adapter facade bridge command
observer visitor iterator composite decorator proxy singleton chain mediator memento state
template visitor anticorruption aggregate entity value domain service repository event
snapshot journal wal consensus gossip heartbeat lease epoch quorum shard pluggable durable
idempotent retries backoff circuit breaker bulkhead throttle ratelimit quota sandbox canary
bluegreen feature parity contract schema registry stream table changelog topic consumer
producer broker offset lag commit partition rebalance exactly atmost atleast idempotent
payload header chunk frame packet segment window handshake ack nack checksum crc hash
base64 gzip brotli zlib deflate snappy lz pigeonhole entropy random oracle nonce seed prng
gambler monty bayes markov poisson gaussian median quantile outlier variance covariance
skew kurtosis histogram scatter correlogram violin swarm lollipop dendrogram sankey chord
treemap sunburst waffle chord gauge slider stepper toggle switch radio checkbox dropdown
datepicker upload download progress spinner skeleton shimmer placeholder tooltip popover
modal overlay drawer bottomsheet snackbar fab chip badge avatar tile card list grid Masonry
parallax sticky infinite virtualized lazy suspense hydration island ssr ssg isr prerender
postcss sass less stylus tailwind bootstrap material antd chakra mantine radix headless
ariafocus tabindex landmark sronly alt caption transcript signlanguage braille dyslexia
contrast luminance hue saturation brightness cmyk rgb hsv hsl pantone hexcodes gradient
opacity blend mask clip path transform perspective translate rotate scale skew matrix
bezier spline nurbs subdivision voxel quaternion euler gimbal lookat ortho frustum culling
zbuffer stencil raster raytrace pathtrace photon radiance irradiance albedo roughness metal
fresnel subsurface anisotropic parallax occlusion displacement tessellation compute shader
warpgroup block grid fence atomic mutex spinlock semaphore barrier condvar future channel
select goroutine defer panic recover mod vendor workspace airuf bazel pants gradle maven
ant make ninja cmake meson conda pip virtualenv poetry pdm npm yarn pnpm bower composer
cocoapods carthage scons buck please nix guix brew choco scoop winget apt dnf pacman zypper
portage emerge snap flatpak appimage msi deb rpm tar gzip bzip zstd squashfs iso vmdk qcow
"""

WORDS = sorted({w.strip().lower() for w in WORDS.split() if w.strip().isalpha() and w.strip().islower()})
assert len(WORDS) >= 500, f"words short: {len(WORDS)}"
print(f"  words: {len(WORDS)} unique tech words")


def git_more_tasks():
    out = []
    # branch-parameterized extras
    for b in BRANCHES:
        out.append(mcq(f"Replay your current branch's commits on top of the latest '{b}'.",
                       f"git rebase {b}", f"git replay {b}", f"git refresh {b}", f"git merge {b} --top"))
    for b in BRANCHES:
        out.append(mcq(f"Merge '{b}' into your current branch.",
                       f"git merge {b}", f"git combine {b}", f"git attach {b}", f"git branch-merge {b}"))
    for b in BRANCHES:
        out.append(mcq(f"Create AND switch to a new branch '{b}' using the MODERN command.",
                       f"git switch -c {b}", f"git checkout {b}", f"git branch-new {b}", f"git switch-make {b}"))
    # file-parameterized extras
    for f in FILES:
        out.append(mcq(f"Check whether '{f}' is matched by a .gitignore rule.",
                       f"git check-ignore {f}", f"git ignore-check {f}", f"git is-ignored {f}", f"git status --ignored {f}"))
        out.append(mcq(f"Rename the tracked file '{f}' to '{f}.bak' in Git and on disk.",
                       f"git mv {f} {f}.bak", f"git rename {f} {f}.bak", f"git move --tracked {f} {f}.bak",
                       f"mv {f} {f}.bak && git add"))
        out.append(mcq(f"Show the full history of '{f}' including renames.",
                       f"git log --follow {f}", f"git history --track {f}", f"git log --renames on {f}",
                       f"git show all {f}"))
        out.append(mcq(f"Unstage ONLY the file '{f}' (modern command), keeping its changes.",
                       f"git restore --staged {f}", f"git unstage {f}", f"git reset {f} --hard",
                       f"git checkout --staged {f}"))
        out.append(mcq(f"Remove '{f}' from Git AND from the disk.",
                       f"git rm {f}", f"git delete {f}", f"git untrack {f}", f"git remove --cached {f}"))
    # numeric families
    for n in range(1, 13):
        out.append(mcq(f"Show only the last {n} commit(s), one per line.",
                       f"git log --oneline -{n}", f"git log -last {n}", f"git history -n {n}",
                       f"git log --oneline --max {n}"))
    for n in range(1, 9):
        out.append(mcq(f"See what changed in the commit {n} step(s) before HEAD.",
                       f"git show HEAD~{n}", f"git show HEAD-{n}", f"git diff HEAD~{n} --show",
                       f"git open HEAD^{n}"))
    # branch-pair diffs
    for a, b in [("main", "develop"), ("main", "feature-login"), ("develop", "release-2.0"),
                 ("main", "release-1.5"), ("develop", "feature-search"), ("main", "hotfix-payment"),
                 ("develop", "bugfix-header"), ("main", "experiment-api")]:
        out.append(mcq(f"Compare branch '{b}' against '{a}' (what changed in '{b}').",
                       f"git diff {a}..{b}", f"git diff --between {a} {b}", f"git compare {a} {b}",
                       f"git log {a} minus {b}"))
    # stash extras
    out += [
        mcq("Drop the most recent stash entry.",
            "git stash drop", "git stash remove", "git stash delete last", "git stash clear one"),
        mcq("Apply the stash entry {1} WITHOUT removing it from the stash list.",
            "git stash apply stash@{1}", "git stash pop stash@{1}", "git stash get 1",
            "git apply --keep stash 1"),
        mcq("Delete ALL stash entries at once.",
            "git stash clear", "git stash drop --all", "git stash remove *", "git stash purge"),
        mcq("Create a new branch from your stashed changes.",
            "git stash branch fix-branch", "git stash new-branch fix-branch",
            "git branch stash fix-branch", "git checkout stash fix-branch"),
    ]
    # tag extras
    for tag in TAGS:
        out.append(mcq(f"Show details of the tag {tag}.",
                       f"git show {tag}", f"git tag info {tag}", f"git describe {tag}", f"git open tag {tag}"))
        out.append(mcq(f"Delete the local tag {tag}.",
                       f"git tag -d {tag}", f"git tag --remove {tag}", f"git delete tag {tag}",
                       f"git push origin --tag {tag}"))
    # merge/rebase variants
    out += [
        mcq("Merge 'develop' but force a real merge commit instead of fast-forward.",
            "git merge --no-ff develop", "git merge --manual develop", "git merge develop --commit-only",
            "git merge --no-ff-only develop"),
        mcq("Squash all commits of 'feature-x' into ONE commit on your branch.",
            "git merge --squash feature-x", "git squash feature-x", "git merge feature-x --one",
            "git commit --combine feature-x"),
        mcq("Update your branch with origin/main by downloading AND rebasing in one step.",
            "git pull --rebase origin main", "git fetch --rebase origin main",
            "git pull origin main --replay", "git rebase pull origin main"),
        mcq("Push the CURRENT branch without typing its name.",
            "git push origin HEAD", "git push origin .", "git push --current",
            "git push origin @branch"),
    ]
    # cleaning
    out += [
        mcq("Preview which untracked files WOULD be deleted by git clean.",
            "git clean -n", "git clean --dry", "git clean --preview-mode", "git clean -p"),
        mcq("Delete all untracked files and folders (not ignored ones).",
            "git clean -fd", "git clean -rfx", "git clean --delete-all", "git rm --untracked"),
        mcq("Delete untracked files INCLUDING ignored ones (dangerous).",
            "git clean -fdx", "git clean -fd", "git clean --ignored-keep", "git clean -all-safe"),
        mcq("List all tracked files in the index.",
            "git ls-files", "git list files", "git tracked", "git index --list"),
    ]
    # remote extras
    for old, new in [("origin", "upstream"), ("upstream", "origin"), ("origin", "backup")]:
        out.append(mcq(f"Rename the remote '{old}' to '{new}'.",
                       f"git remote rename {old} {new}", f"git remote mv {old} {new}",
                       f"git rename remote {old} {new}", f"git remote set-name {old} {new}"))
    for r in ["origin", "backup", "upstream"]:
        out.append(mcq(f"Show full details (URLs, branches) of the remote '{r}'.",
                       f"git remote show {r}", f"git remote info {r}", f"git remote --detail {r}",
                       f"git show remote {r}"))
        out.append(mcq(f"Change the URL of the remote '{r}'.",
                       f"git remote set-url {r} <url>", f"git remote url {r} <url>",
                       f"git remote change {r} <url>", f"git remote edit {r} <url>"))
    out.append(mcq("Fetch ONLY the branch 'develop' from origin.",
                   "git fetch origin develop", "git pull origin develop --no-merge",
                   "git fetch --branch develop", "git get develop"))
    out.append(mcq("Clone only the most recent commit (shallow clone).",
                   "git clone --depth 1 <url>", "git clone --single <url>",
                   "git clone -1 <url>", "git clone --shallow-one <url>"))
    for b in BRANCHES[:4]:
        out.append(mcq(f"Clone a repo and immediately check out its branch '{b}'.",
                       f"git clone -b {b} <url>", f"git clone --at {b} <url>",
                       f"git clone <url> {b} --only", f"git checkout-clone {b} <url>"))
    # history search
    for p in ["login", "fix", "style", "password", "todo", "api"]:
        out.append(mcq(f'Search commit MESSAGES for the word "{p}".',
                       f'git log --grep={p}', f'git search "{p}"', f'git log --find {p}',
                       f'git log --message-contains {p}'))
    for who in ["Ram", "Sita", "Hari", "Gita"]:
        out.append(mcq(f"List commits authored by {who}.",
                       f"git log --author={who}", f"git log --by {who}", f"git commits {who}",
                       f"git log --writer {who}"))
    # restore/checkout from history
    for f in FILES[:6]:
        out.append(mcq(f"Restore '{f}' to the version from 2 commits ago (keep it staged-free).",
                       f"git restore --source=HEAD~2 {f}", f"git checkout HEAD~2 {f} --hard",
                       f"git restore {f} HEAD~2", f"git reset HEAD~2 {f}"))
        out.append(mcq(f"Bring '{f}' from the branch 'develop' into your current branch.",
                       f"git restore --source=develop {f}", f"git copy develop {f}",
                       f"git checkout develop {f} --into", f"git merge develop --file {f}"))
    # force-delete branches
    for b in BRANCHES[:6]:
        out.append(mcq(f"Force-delete the local branch '{b}' even though it was never merged.",
                       f"git branch -D {b}", f"git branch -d! {b}", f"git branch --force-drop {b}",
                       f"git delete -f {b}"))
    # amend / commit extras
    for m in MSGS[:4]:
        out.append(mcq(f'Commit all tracked modified files at once with the message "{m}" (skip staging).',
                       f'git commit -a -m "{m}"', f'git commit --all-now "{m}"',
                       f'git add . && git commit "{m}"', f'git commit -m "{m}" --include-tracked'))
    out += [
        mcq("Add your staged changes to the LAST commit, keeping its original message.",
            "git commit --amend --no-edit", "git commit --append", "git commit --reuse HEAD",
            "git add --last-commit"),
        mcq("Create an empty commit (no changes) just to mark a point in history.",
            "git commit --allow-empty -m 'mark'", "git commit --empty -m 'mark'",
            "git commit --force -m 'mark'", "git mark -m 'mark'"),
        mcq("Which config command lists ALL current settings with their origin?",
            "git config --list --show-origin", "git config --all --where", "git settings --list",
            "git config --print"),
        mcq("Remove a global config entry (e.g. user.email).",
            "git config --global --unset user.email", "git config --global --delete user.email",
            "git config --remove user.email global", "git unset user.email"),
        mcq("Show which remote branch your local branch is tracking.",
            "git branch -vv", "git branch --tracking", "git status --upstream", "git remote -t"),
        mcq("Recover into a NEW branch after landing in detached HEAD.",
            "git switch -c rescue-branch", "git checkout --new-rescue rescue-branch",
            "git branch restore rescue-branch", "git attach rescue-branch"),
        mcq("Add a second work directory for another branch without cloning again.",
            "git worktree add ../hot -b hotfix", "git clone-branch ../hot hotfix",
            "git second-checkout ../hot", "git branch-clone hotfix ../hot"),
        mcq("Create the alias 'st' for 'status'.",
            "git config --global alias.st status", "git alias st=status",
            "git config --global st=status", "git shortcut st status"),
        mcq("Describe the closest reachable tag relative to the current commit.",
            "git describe", "git nearest-tag", "git tag --closest", "git which-tag"),
        mcq("Blame lines 10 to 20 of a file only.",
            "git blame -L 10,20 file", "git blame --range 10-20 file",
            "git blame file 10:20", "git lines 10 20 file"),
    ]
    # last batch
    for b in BRANCHES[8:]:
        out.append(mcq(f"Push the local branch '{b}' to 'origin' for the first time, setting its upstream.",
                       f"git push -u origin {b}", f"git push origin --track {b}", f"git upload origin {b}",
                       f"git push --set origin {b}"))
    for b in ["develop", "main", "feature-login", "release-2.0", "bugfix-header", "hotfix-payment"]:
        out.append(mcq(f"Point your current branch's upstream to 'origin/{b}'.",
                       f"git branch --set-upstream-to=origin/{b}", f"git branch --track-origin {b}",
                       f"git remote bind {b}", f"git branch -u set {b}"))
    for h in HASHES:
        out.append(mcq(f"Create tag 'v1.0.0' on the specific commit {h}.",
                       f"git tag v1.0.0 {h}", f"git tag --on {h} v1.0.0", f"git mark {h} v1.0.0",
                       f"git tag at {h}"))
    for tag in TAGS:
        out.append(mcq(f"Delete the tag {tag} on the REMOTE 'origin'.",
                       f"git push origin :refs/tags/{tag}", f"git tag -d origin {tag}",
                       f"git push --delete-tag origin {tag}", f"git remote tag remove {tag}"))
    for b in BRANCHES[:4]:
        out.append(mcq(f"List commits that are on '{b}' but NOT on 'main'.",
                       f"git log main..{b}", f"git log {b} --not-in main", f"git diff main {b} --commits",
                       f"git unshared {b}"))
    for h in HASHES:
        out.append(mcq(f"List local branches that contain the commit {h}.",
                       f"git branch --contains {h}", f"git branches with {h}", f"git which-branch {h}",
                       f"git log --branches {h}"))
    for since in ["yesterday", "1 week ago", "2026-01-01", "1 month ago", "3 days ago", "last friday"]:
        out.append(mcq(f"Show commits made since {since}.",
                       f'git log --since="{since}"', f'git log --after-date "{since}"',
                       f'git log --newer "{since}"', f'git log --from "{since}" only'))
    out += [
        mcq("Download tags from the remote as part of fetching.",
            "git fetch --tags", "git pull tags", "git fetch --include-tags=1", "git tags fetch"),
        mcq("List only tags starting with 'v1'.",
            "git tag -l 'v1*'", "git tag --prefix v1", "git tags list v1", "git tag --match-start v1"),
        mcq("Show a summary of changed files and insertions/deletions per commit.",
            "git log --stat", "git log --summary-lines", "git show --counts", "git log --files-stats"),
        mcq("Show only the file names changed in the last commit.",
            "git show --name-only HEAD", "git show --files HEAD", "git diff --names HEAD",
            "git log --name HEAD"),
        mcq("Switch back to the previous branch (modern command).",
            "git switch -", "git switch back", "git switch last", "git switch previous"),
        mcq("Discard ALL local modifications in the working tree (dangerous).",
            "git restore .", "git discard .", "git clean .", "git undo ."),
        mcq("Prepare a 'fixup' commit targeting an older commit (for later autosquash).",
            "git commit --fixup abc1234", "git fixup abc1234", "git commit --target abc1234",
            "git commit -m fixup --to abc1234"),
    ]
    return out


# ============================================================
# 4) BUG HUNTER — shared language pools
#    Every challenge stored ONCE; fields compose pools (bugFieldPools)
# ============================================================

def semis(pairs, note="Missing semicolon at the end of line 1 — the statement is not terminated.", diff="easy"):
    pats = []
    for stmt, follow in pairs:
        def gen(s=stmt, f=follow):
            a, v = idv()
            return bug([s.format(a=a, v=v), f.format(a=a, v=v)], 0, note, diff)
        pats.append(gen)
    return pats


# ---------------- PYTHON pool (target 540) ----------------
def python_pool():
    # NOTE: Python has no semicolons — this pool uses colon/indentation/
    # name/logic bugs only.
    def p_colon_if():
        a, v = idv()
        t = v + random.choice([1, 5, 10])
        return bug([f"{a} = {v}", f"if {a} > {t}", "    print('big')"], 1,
                   "Missing colon (:) at the end of the 'if' condition — SyntaxError.", "easy")

    def p_colon_def():
        return bug(["def add(x, y)", "    return x + y"], 0,
                   "Missing colon (:) after the function definition — SyntaxError.", "easy")

    def p_colon_for():
        a, v = idv()
        return bug([f"{a} = [{v}, {v + 1}, {v + 2}]", f"for n in {a}", "    print(n)"], 1,
                   "Missing colon (:) at the end of the 'for' statement — SyntaxError.", "easy")

    def p_assign_if():
        a, v = idv()
        return bug([f"{a} = {v}", f"if {a} = {v}:", "    print('same')"], 1,
                   "Single = assigns instead of comparing — must be == inside the if.", "medium")

    def p_plusequals():
        v = random.choice([2, 4, 7, 9])
        return bug(["total = 0", f"for n in [{v}, {v + 3}, {v + 5}]:", "    total =+ n", "print(total)"], 2,
                   "=+ is not += — this reassigns total to n each loop instead of adding.", "easy")

    def p_index_range():
        a, v = idv()
        return bug([f"{a} = [{v}, {v + 1}, {v + 2}]", f"print({a}[3])"], 1,
                   "IndexError — a 3-item list only has indexes 0, 1 and 2.", "medium")

    def p_str_int():
        v = random.choice([20, 25, 30, 42])
        return bug([f"age = {v}", "print('Age: ' + age)"], 1,
                   "Cannot concatenate str + int — use str(age) or an f-string.", "easy")

    def p_name_typo():
        good, bad = random.choice([("total", "totl"), ("count", "cont"), ("value", "valu"),
                                   ("result", "resut"), ("price", "prce"), ("score", "sore")])
        return bug([f"{good} = {random.choice(VALS)}", f"print({bad})"], 1,
                   f"NameError: '{bad}' is a typo — the variable is named '{good}'.", "easy")

    def p_mutable_default():
        return bug(["def add_item(item, cart=[]):", "    cart.append(item)", "    return cart"], 0,
                   "Mutable default argument — the same list is shared across all calls; use None + create inside.", "hard")

    def p_map_object():
        return bug(["nums = [1, 2, 3]", "squared = map(lambda n: n ** 2, nums)", "print(squared[0])"], 2,
                   "map() returns a lazy map object, not a list — wrap with list(map(...)) before indexing.", "medium")

    def p_except_swallow():
        return bug(["try:", "    value = int(input('Number: '))", "except ValueError:", "    pass",
                    "print('You typed:', value)"], 4,
                   "If the input is invalid, 'value' is never assigned — the except swallows the error and print() raises NameError.", "hard")

    def p_while_offbyone():
        v = random.choice([5, 8, 10])
        return bug(["i = 0", f"items = [{v}, {v + 1}]", "while i <= len(items):", "    print(items[i])",
                    "    i += 1"], 2,
                   "<= runs one step too far — len(items) is 2, so items[2] is out of range; use <.", "medium")

    def p_open_quote():
        return bug(["name = 'world", "print(name)"], 0,
                   "The string is missing its closing quote — SyntaxError (unterminated string literal).", "easy")

    def p_method_typo():
        m = random.choice([("strip", "strp"), ("upper", "uper"), ("lower", "lower2"), ("split", "splt")])
        return bug(["  name = ' hello  '", f"print(name.{m[1]}())"], 1,
                   f"AttributeError — '{m[1]}' is a typo; the method is '{m[0]}()'.", "easy")

    def p_class_self():
        return bug(["class Counter:", "    count = 0", "    def increment():", "        Counter.count += 1"], 2,
                   "Instance method is missing the 'self' parameter — calling it on an instance raises a TypeError.", "hard")

    def p_indent():
        return bug(["def check(x):", "    if x > 0:", "    print('positive')"], 2,
                   "Bad indentation — the print is dedented to the 'def' level, so the if has no body: IndentationError.", "medium")

    def p_floor_div():
        v = random.choice([7, 9, 11])
        return bug([f"total = {v}", "avg = total // 2", "print('Average:', avg)"], 1,
                   "// is floor division — it silently truncates; use / when decimals are expected.", "medium")

    def p_dict_typo():
        return bug(["user = {'name': 'Ram', 'age': 20}", "print(user['nam'])"], 1,
                   "KeyError — 'nam' is a typo; the key is 'name'. Using .get('name') is safer.", "easy")

    def p_range_zero():
        v = random.choice([3, 5, 8])
        return bug([f"for i in range(1, {v}):", f"    print(i)", "print('done')"], 0,
                   "range(1, n) skips index 0 — the classic off-by-one when the loop should cover 0..n-1: use range(n).", "medium")

    pats = [p_colon_if, p_colon_def, p_colon_for, p_assign_if, p_plusequals, p_index_range,
            p_str_int, p_name_typo, p_mutable_default, p_map_object, p_except_swallow,
            p_while_offbyone, p_open_quote, p_method_typo, p_class_self, p_indent,
            p_floor_div, p_dict_typo, p_range_zero]
    return pats


# ---------------- JS pool (target 260) ----------------
def js_pool():
    pats = []
    pats += semis([
        ("const {a} = document.querySelector('.{a}-item')", "{a}.classList.add('visible');"),
        ("let total = price * {v}", "console.log(total);"),
        ("const api = 'https://api.example.com/{a}'", "fetch(api);"),
        ("const saved = localStorage.getItem('{a}')", "console.log(saved);"),
        ("let {a} = {v}", "{a} = {a} + 1;"),
    ])

    def j_eq_strict():
        v = random.choice([5, 10, 25])
        return bug([f"const level = '{v}';", f"if (level === {v}) {{", "  console.log('match');", "}"], 1,
                   "Strict === never matches string vs number — the condition is always false; convert or use ==.", "medium")

    def j_getelem_hash():
        a = random.choice(IDS)
        return bug([f"const form = document.getElementById('#{a}');", "form.addEventListener('submit', save);"], 0,
                   "getElementById takes a plain id WITHOUT '#' — '#…' is querySelector syntax.", "medium")

    def j_query_no_dot():
        return bug(["const card = document.querySelector('card');", "card.remove();"], 0,
                   "querySelector needs a CSS selector — a class needs '.card', an id needs '#card'.", "medium")

    def j_listener_typo():
        return bug(["document.getElementById('btn').addEventListner('click', go);", "function go() {", "  console.log('hi');", "}"], 0,
                   "Typo: 'addEventListner' should be 'addEventListener'.", "easy")

    def j_missing_await():
        return bug(["async function loadData() {", "  const data = fetch('/api/data').then(r => r.json());",
                    "  console.log(data);", "}"], 1,
                   "Missing 'await' before the fetch chain — 'data' is a pending Promise, not the JSON.", "hard")

    def j_offbyone():
        v = random.choice([3, 5, 10])
        return bug([f"const items = new Array({v}).fill(0);", "for (let i = 0; i <= items.length; i++) {",
                    "  console.log(items[i]);", "}"], 1,
                   "<= reads items[length] — one past the end (undefined). Use <.", "medium")

    def j_reduce_return():
        return bug(["const total = items.reduce((sum, item) => {", "  sum + item.price;", "}, 0);"], 1,
                   "Missing 'return' inside the reduce callback — the accumulator never updates.", "medium")

    def j_closure_var():
        return bug(["var funcs = [];", "for (var i = 0; i < 3; i++) {", "  funcs.push(function () { return i; });", "}",
                    "console.log(funcs[0]());"], 2,
                   "var is function-scoped — every closure shares the same i (returns 3). Use let.", "hard")

    def j_call_not_ref():
        return bug(["function handleClick() {", "  console.log('click');", "}",
                    "btn.onclick = handleClick();"], 3,
                   "handleClick() CALLS the function immediately; assign the reference: onclick = handleClick.", "medium")

    def j_res_json():
        return bug(["fetch('/api/x')", "  .then(res => res.json)", "  .then(data => render(data));"], 1,
                   "res.json is a method — it must be CALLED: res.json().", "easy")

    def j_const_reassign():
        a = random.choice(IDS)
        return bug([f"const {a} = {random.choice(VALS)};", f"{a} = {a} + 1;", f"console.log({a});"], 1,
                   "const cannot be reassigned — TypeError. Use let for values that change.", "easy")

    def j_foreach_return():
        return bug(["const cleaned = items.forEach(function (item) {", "  return item.trim();", "});",
                    "console.log(cleaned[0]);"], 0,
                   "forEach returns undefined — use map() when you need a new array.", "medium")

    def j_push_immute():
        return bug(["function addTodo(todo) {", "  todos.push(todo);", "  setTodos(todos);", "}"], 1,
                   "Mutating the existing array directly — downstream code can't detect the change; create a new array instead.", "hard")

    pats += [j_eq_strict, j_getelem_hash, j_query_no_dot, j_listener_typo, j_missing_await,
             j_offbyone, j_reduce_return, j_closure_var, j_call_not_ref, j_res_json,
             j_const_reassign, j_foreach_return, j_push_immute]
    return pats


# ---------------- HTML/CSS pool (target 180) ----------------
def htmlcss_pool():
    def h_close_mismatch():
        pair = random.choice([("ul", "li"), ("div", "p"), ("span", "b"), ("form", "div")])
        return bug([f"<{pair[0]} class='box'>", f"  <{pair[1]}>Text</{pair[1]}>", f"<{pair[1]}>"], 2,
                   f"Closing tag mismatch — the outer element must close with </{pair[0]}>, not another <{pair[1]}>.", "easy")

    def h_missing_alt():
        return bug(["<button style='width:16px;height:16px'>", "  <img src='delete-icon.png'>", "</button>"], 1,
                   "Icon button has no alt text / aria-label — screen readers can't tell what it does.", "easy")

    def h_label_for():
        return bug(["<form>", "  <label>Email</label>", "  <input type='email' id='user-email'>", "</form>"], 1,
                   "The label isn't linked to the input — add for='user-email' matching the input id.", "medium")

    def h_dup_id():
        return bug(["<input id='email'>", "<input id='email'>"], 1,
                   "Duplicate id — ids must be unique; labels/scripts bind to the FIRST match only.", "medium")

    def h_unquoted():
        return bug(["<a href=index.html>Home</a>"], 0,
                   "Attribute value must be quoted: href='index.html' — unquoted values break with spaces/special chars.", "easy")

    def c_prop_typo():
        p = random.choice([("color", "colr"), ("border", "bortder"), ("font-size", "fon-size"),
                           ("background", "bakground"), ("width", "widht"), ("height", "heigth")])
        return bug([".card {", f"  {p[1]}: red;", "  padding: 10px;", "}"], 1,
                   f"CSS typo: '{p[1]}' is not a property — the browser ignores it; it should be '{p[0]}'.", "easy")

    def c_missing_semi():
        return bug([".box {", "  color: #ffffff", "  background: #1e293b;", "}"], 1,
                   "Missing semicolon after the value — the next declaration gets swallowed into an invalid one.", "easy")

    def c_missing_colon():
        return bug([".title {", "  color #ffffff;", "}"], 1,
                   "Missing colon between property and value — invalid declaration.", "easy")

    def c_bad_value():
        return bug([".text {", "  color: 15px;", "}"], 1,
                   "Wrong value type — color expects a color (#fff, red, rgb()), not a length like 15px.", "easy")

    def c_no_unit():
        return bug([".container {", "  width: 100;", "}"], 1,
                   "Length is missing its unit — width needs px/%/rem etc. (0 is the only unitless length).", "easy")

    def c_selector_mismatch():
        return bug(["<div id='header'></div>", "<style>", "  .header { color: red; }", "</style>"], 2,
                   "The element has id='header' but the CSS targets class .header — use #header.", "medium")

    def c_flex_prop():
        return bug([".row {", "  display: block;", "  justify-content: space-between;", "}"], 1,
                   "justify-content only works in flex/grid containers — display must be flex (or grid).", "medium")

    return [h_close_mismatch, h_missing_alt, h_label_for, h_dup_id, h_unquoted,
            c_prop_typo, c_missing_semi, c_missing_colon, c_bad_value, c_no_unit,
            c_selector_mismatch, c_flex_prop]


# ---------------- Node/MERN pool (target 130) ----------------
def node_pool():
    def n_start():
        return bug(["const express = require('express');", "const app = express();",
                    "app.get('/', (req, res) => res.send('hi'));", "app.start(3000);"], 3,
                   "There is no app.start() — Express listens with app.listen(3000).", "easy")

    def n_await_save():
        return bug(["router.post('/api/items', async (req, res) => {", "  const item = new Item(req.body);",
                    "  item.save();", "  res.json(item);", "});"], 2,
                   "Missing 'await' before item.save() — the response is sent before the document is saved and errors are lost.", "medium")

    def n_route_comma():
        return bug(["app.get('/api/users', (req, res) => {", "  res.json(users);", "});",
                    "app.post('/api/users' (req, res) => {", "  users.push(req.body);", "});"], 3,
                   "Missing comma between the route path and the handler in app.post().", "easy")

    def n_model_case():
        return bug(["const orderSchema = new mongoose.Schema({ total: Number });",
                    "const Order = mongoose.Model('Order', orderSchema);"], 1,
                   "mongoose.Model is not the model factory — use lowercase mongoose.model().", "medium")

    def n_middleware_order():
        return bug(["const app = express();", "app.post('/api/data', (req, res) => res.json({}));",
                    "app.use(cors());"], 2,
                   "cors() middleware is registered AFTER the route, so it never applies to it — middleware must come first.", "hard")

    def n_body_parser():
        return bug(["const app = express();", "app.post('/api/x', (req, res) => {",
                    "  console.log(req.body.name);", "});"], 2,
                   "req.body is undefined because express.json() middleware was never registered.", "medium")

    def n_await_find():
        return bug(["app.get('/api/users', async (req, res) => {", "  const users = User.find();",
                    "  res.json(users);", "});"], 1,
                   "Missing 'await' — User.find() returns a Query/Promise, not documents.", "medium")

    def n_status_before():
        return bug(["app.get('/old', (req, res) => {", "  res.send('moved');", "  res.redirect('/new');", "});"], 2,
                   "Headers were already sent by res.send() — you cannot redirect afterwards.", "hard")

    def n_undefined_var():
        a, b = random.choice([("users", "user"), ("items", "item"), ("orders", "order")])
        return bug([f"const {a} = load{a.capitalize()}();", f"res.json({b});"], 1,
                   f"Variable mismatch — '{b}' is undefined; the data is stored in '{a}'.", "easy")

    def n_missing_next():
        return bug(["app.use((req, res, next) => {", "  console.log(req.url);", "});"], 1,
                   "Custom middleware never calls next() — every request hangs, nothing after this runs.", "hard")

    return [n_start, n_await_save, n_route_comma, n_model_case, n_middleware_order,
            n_body_parser, n_await_find, n_status_before, n_undefined_var, n_missing_next]


# ---------------- React pool (target 130) ----------------
def react_pool():
    def r_key():
        return bug(["function ItemList({ items }) {", "  return (", "    <ul>",
                    "      {items.map(item => <li>{item.name}</li>)}", "    </ul>", "  );", "}"], 3,
                   "Missing 'key' prop when rendering a list — React needs a stable unique key per mapped item.", "easy")

    def r_onclick_call():
        return bug(["function App() {", "  function handleClick() { console.log('x'); }",
                    "  return <button onClick={handleClick()}>Go</button>;", "}"], 2,
                   "onClick={handleClick()} invokes during render — pass the reference: onClick={handleClick}.", "medium")

    def r_effect_deps():
        return bug(["function Counter() {", "  const [count, setCount] = useState(0);",
                    "  useEffect(() => { setCount(count + 1); });", "  return <div>{count}</div>; }"], 2,
                   "useEffect has no dependency array — it runs after EVERY render, causing an infinite update loop.", "hard")

    def r_mutate():
        return bug(["function addTodo(todo) {", "  todos.push(todo);", "  setTodos(todos);", "}"], 1,
                   "Mutating state directly — React compares references, so it may never re-render; build a new array.", "hard")

    def r_setter_typo():
        return bug(["function Counter() {", "  const [count, setCount] = useState(0);",
                    "  return <button onClick={() => setCunt(count + 1)}>+1</button>;", "}"], 2,
                   "Typo: setCunt is not defined — the setter from useState is setCount.", "easy")

    def r_missing_import():
        return bug(["function Counter() {", "  const [count, setCount] = useState(0);",
                    "  return <div>{count}</div>;", "}"], 1,
                   "useState is used but never imported from 'react' — ReferenceError.", "easy")

    def r_this_props():
        return bug(["function UserCard(props) {", "  return <div>{this.props.name}</div>;", "}"], 1,
                   "Functional components have no 'this' — use {props.name}.", "medium")

    def r_guard():
        return bug(["function Profile({ user }) {", "  return <div>{user.name}</div>;", "}"], 1,
                   "user is undefined while loading — user.name crashes; guard with {user?.name}.", "medium")

    def r_map_return():
        return bug(["function List({ items }) {", "  return (", "    <div>",
                    "      {items.map(item => { item.name })}", "    </div>", "  );", "}"], 3,
                   "Curly-arrow body needs an explicit return — { item.name } computes and discards; return item.name.", "hard")

    def r_stale_interval():
        return bug(["function Timer() {", "  const [s, setS] = useState(0);", "  useEffect(() => {",
                    "    const id = setInterval(() => setS(s + 1), 1000);", "    return () => clearInterval(id);",
                    "  }, []);", "  return <div>{s}</div>; }"], 3,
                   "Stale closure — 's' is captured once at 0; use the functional update setS(x => x + 1).", "hard")

    return [r_key, r_onclick_call, r_effect_deps, r_mutate, r_setter_typo, r_missing_import,
            r_this_props, r_guard, r_map_return, r_stale_interval]


# ---------------- Next.js pool (target 70) ----------------
def next_pool():
    def x_link():
        return bug(["import Link from 'next/link';", "export default function Nav() {",
                    "  return <Link href='/about'>About<Link>;", "}"], 2,
                   "Closing tag must be </Link>, not another opening <Link>.", "easy")

    def x_state():
        return bug(["'use client'", "import { useState } from 'react';",
                    "export default function Counter() {", "  const [count, setCount] = useState();",
                    "  return <button onClick={() => setCount(count + 1)}>{count}</button>; }"], 3,
                   "useState() without an initial value — count is undefined, so count + 1 is NaN.", "medium")

    def x_await():
        return bug(["export async function getServerSideProps() {",
                    "  const res = fetch('https://api.example.com/data');", "  const data = res.json();",
                    "  return { props: { data } }; }"], 1,
                   "Missing 'await' before fetch() — res is a pending Promise and res.json() fails.", "hard")

    def x_params():
        return bug(["export function generateStaticParams() {", "  return fetch('/api/posts'); }"], 1,
                   "generateStaticParams must return an array of param objects, not a raw Response.", "medium")

    def x_client():
        return bug(["import { useState } from 'react';", "export default function Counter() {",
                    "  const [n, setN] = useState(0);", "  return <button onClick={() => setN(n + 1)}>{n}</button>; }"], 0,
                   "useState/onClick need client interactivity — the file is missing the 'use client' directive at the top.", "hard")

    def x_image():
        return bug(["import Image from 'next/image';", "export default function Logo() {",
                    "  return <Image src='/logo.png' width={100} height={100} />", "}"], 2,
                   "The return statement is not terminated with ';' — inconsistent style that can trip ASI in edge cases.", "easy")

    def x_map_key():
        return bug(["export default function Tags({ tags }) {", "  return (", "    <div>",
                    "      {tags.map(t => <span>{t}</span>)}", "    </div>", "  ); }"], 3,
                   "List rendered without a 'key' prop on each mapped element — React needs a unique key.", "easy")

    return [x_link, x_state, x_await, x_params, x_client, x_image, x_map_key]


# ---------------- PHP pool (target 190) ----------------
def php_pool():
    def pp_dollar():
        a = random.choice(["name", "total", "count", "user"])
        return bug([f"${a} = 'hello';", f"echo {a};"], 1,
                   "PHP variables always need the $ prefix — {a} without $ is treated as a constant (warning/error).", "easy")

    def pp_semi():
        a = random.choice(["name", "total", "count"])
        return bug([f"${a} = 10", f"echo ${a};"], 0,
                   "Missing semicolon at the end of the assignment statement.", "easy")

    def pp_assign():
        v = random.choice([5, 10, 20])
        return bug([f"$level = {v};", f"if ($level = 10) {{", "  echo 'ten';", "}"], 1,
                   "= assigns (always truthy here) instead of comparing — use == or ===.", "medium")

    def pp_concat():
        return bug(["$name = 'Ram';", "echo 'Hello ' + $name;"], 1,
                   "PHP concatenation uses the dot (.), not + — '+' converts strings to numbers.", "easy")

    def pp_quote():
        return bug(["echo 'Hello World;"], 0,
                   "Missing closing quote — PHP string is unterminated (parse error).", "easy")

    def pp_array_comma():
        return bug(["$cfg = array(", "  'debug' => true", "  'log' => false", ");"], 1,
                   "Missing comma between array items — PHP parse error.", "easy")

    def pp_echo_typo():
        return bug(["$msg = 'hi';", "eco $msg;"], 1,
                   "Typo: 'eco' should be 'echo'.", "easy")

    def pp_header():
        return bug(["echo 'Starting...';", "header('Location: /home');"], 1,
                   "header() must run BEFORE any output — the echo already sent headers ('headers already sent').", "hard")

    def pp_interp():
        return bug(["$user = ['name' => 'Ram'];", "echo \"Welcome $user['name']\";"], 1,
                   "Inside double quotes, array access needs braces: {$user['name']}.", "medium")

    def pp_foreach():
        return bug(["$items = [1, 2, 3];", "foreache ($items as $item) {", "  echo $item;", "}"], 1,
                   "Typo: 'foreache' should be 'foreach'.", "easy")

    def pp_isnull():
        return bug(["if (isset($email)) {", "  echo $email;", "} else {", "  echo isst($email);", "}"], 3,
                   "Typo: 'isst' should be 'isset' (or empty).", "easy")

    def pp_sql():
        return bug(["$sql = \"SELECT * FROM users WHERE name = '$name'\";", "$res = mysqli_query($conn, $sql);"], 0,
                   "User input concatenated straight into SQL — SQL injection risk; use prepared statements.", "hard")

    return [pp_dollar, pp_semi, pp_assign, pp_concat, pp_quote, pp_array_comma,
            pp_echo_typo, pp_header, pp_interp, pp_foreach, pp_isnull, pp_sql]


# ---------------- Laravel pool (target 70) ----------------
def laravel_pool():
    def l_semi():
        return bug(["Route::get('/home', function () {", "    return view('home')", "});"], 1,
                   "Missing semicolon after return view('home').", "easy")

    def l_where():
        return bug(["public function search($q) {", "    return Product::where('name', 'LIKE' \"%$q%\")->get();", "}"], 1,
                   "Missing comma between 'LIKE' and the pattern — where() call breaks.", "medium")

    def l_fillable():
        return bug(["class Post extends Model {", "    protected $fillable = ['title', 'body']", "}"], 1,
                   "Missing semicolon after the $fillable array.", "easy")

    def l_var():
        a = random.choice([("users", "user"), ("posts", "post"), ("orders", "order")])
        return bug(["public function index() {", f"    ${a[0]} = {a[0].capitalize()}::all();",
                    f"    return view('{a[0]}.index', ['{a[0]}' => ${a[1]}]);", "}"], 2,
                   f"Variable mismatch — the data is in ${a[0]} but the view receives undefined ${a[1]}.", "medium")

    def l_route_order():
        return bug(["Route::get('/posts/{id}', [PostController::class, 'show']);",
                    "Route::get('/posts/create', [PostController::class, 'create']);"], 0,
                   "The wildcard '/posts/{id}' is registered BEFORE '/posts/create' — 'create' is swallowed as an id.", "hard")

    def l_all_paren():
        return bug(["public function index() {", "    $posts = Post::all;", "    return view('posts', compact('posts'));", "}"], 1,
                   "Post::all is missing parentheses — it passes the method itself, not the results.", "easy")

    def l_compact():
        return bug(["public function index() {", "    $posts = Post::all();", "    return view('posts', compact('post'));", "}"], 2,
                   "compact('post') references a variable named $post — the data is in $posts (plural).", "medium")

    return [l_semi, l_where, l_fillable, l_var, l_route_order, l_all_paren, l_compact]


# ---------------- Django pool (target 70) ----------------
def django_pool():
    def dj_render():
        return bug(["from django.shortcuts import render", "", "def index(request):",
                    "    return render('home.html')"], 3,
                   "render() needs the request first: render(request, 'home.html') — TypeError otherwise.", "easy")

    def dj_all():
        return bug(["def list_posts(request):", "    posts = Post.objects.all",
                    "    return render(request, 'list.html', {'posts': posts})"], 1,
                   "Post.objects.all is missing () — it passes the method itself, not the queryset.", "easy")

    def dj_valid():
        return bug(["def register(request):", "    form = RegisterForm(request.POST)",
                    "    if form.is_valid:", "        form.save()"], 2,
                   "is_valid is a method — without () the condition is always truthy (method object).", "medium")

    def dj_filter():
        return bug(["def products(request):", "    data = Product.objects.filter(price > 100)",
                    "    return render(request, 'p.html', {'data': data})"], 1,
                   "Django filters need field__gt=100 lookup syntax, not Python operators.", "medium")

    def dj_path():
        return bug(["urlpatterns = [", "    path('posts/', views.post_list, name='post_list')", "]"], 1,
                   "Missing comma after the path() entry — breaks the urlpatterns list.", "easy")

    def dj_delete():
        return bug(["def remove(request, id):", "    order = Order.objects.get(id=id)", "    order.delete",
                    "    return redirect('orders')"], 2,
                   "order.delete is a method reference without () — the order is never actually deleted.", "medium")

    def dj_maxdigit():
        return bug(["class Product(models.Model):",
                    "    price = models.DecimalField(max_digit=10, decimal_places=2)"], 1,
                   "Typo — it must be max_digits (plural).", "easy")

    return [dj_render, dj_all, dj_valid, dj_filter, dj_path, dj_delete, dj_maxdigit]


# ---------------- WordPress pool (target 70) ----------------
def wp_pool():
    def w_hook():
        return bug(["function my_scripts() {", "    wp_enqueue_style('main', get_stylesheet_uri());", "}",
                    "add_action('wp_enqueue_script', 'my_scripts');"], 3,
                   "Wrong hook name — it must be 'wp_enqueue_scripts' (plural).", "easy")

    def w_shortcode():
        return bug(["function greet($atts) {", "    return 'Hello';", "}",
                    "add_shortcode('greet' 'greet');"], 3,
                   "Missing comma between the shortcode tag and the callback name.", "easy")

    def w_args():
        return bug(["$args = array(", "    'post_type' => 'post'", "    'posts_per_page' => 5", ");",
                    "$q = new WP_Query($args);"], 1,
                   "Missing comma between the array items.", "easy")

    def w_theme():
        return bug(["function setup() {", "    add_theme_support('post-thumbnails')", "}",
                    "add_action('after_setup_theme', 'setup');"], 1,
                   "Missing semicolon after add_theme_support(...).", "easy")

    def w_loop():
        return bug(["<?php if (have_posts()) : ?>", "  <?php while (have_posts()) : the_post(); ?>",
                    "    <h2><?php the_title(); ?></h2>", "<?php endwhile; ?>"], 3,
                   "The loop closes with endwhile but the outer if never gets its endif;.", "medium")

    def w_header():
        return bug(["getheader();", "while (have_posts()) {", "  the_post();", "}"], 0,
                   "Typo: 'getheader' should be 'get_header'.", "easy")

    def w_haveposts():
        return bug(["<?php if (have_posts) : ?>", "  <?php the_post(); ?>", "<?php endif; ?>"], 0,
                   "have_posts is a function — it needs parentheses: have_posts().", "medium")

    return [w_hook, w_shortcode, w_args, w_theme, w_loop, w_header, w_haveposts]


# ---------------- Dart/Flutter pool (target 500) ----------------
def dart_pool():
    pats = []
    pats += semis([
        ("int count = {v}", "void increment() {{"),
        ("String title = 'My App'", "print(title);"),
        ("final {a} = <String>['a', 'b']", "print({a}.length);"),
        ("var loaded = {a} > {v}", "print(loaded);"),
        ("double rate = {v}.0", "print(rate);"),
        ("const maxRetry = {v}", "print(maxRetry);"),
    ], "Missing semicolon at the end of the statement — Dart requires it (no ASI like JavaScript).", "easy")

    def d_setstate():
        return bug(["class _CounterState extends State<Counter> {", "  int count = 0;", "  void increment() {",
                    "    count++;", "  }", "}"], 3,
                   "count++ changes the field but Flutter never rebuilds — wrap it in setState(() { count++; });", "medium")

    def d_await():
        return bug(["Future<void> fetchData() async {", "  final response = http.get(Uri.parse('https://api.example.com/x'));",
                    "  print(response.body);", "}"], 1,
                   "Missing 'await' — response is a Future and .body isn't available yet.", "hard")

    def d_index():
        return bug(["ListView.builder(", "  itemCount: items.length,", "  itemBuilder: (context, index) {",
                    "    return Text(items[index + 1]);", "  },", ")"], 3,
                   "index + 1 overruns the list on the last item — use items[index].", "medium")

    def d_paren():
        return bug(["Widget build(BuildContext context) {", "  return Text('Hello'", "}"], 1,
                   "Missing closing parenthesis in Text('Hello' — and the return needs ';'.", "easy")

    def d_interp():
        return bug(["void show() {", "  int count = 5;", "  print('$counts');", "}"], 2,
                   "Wrong interpolation variable — '$counts' looks up a different name; use '$count' or '${count}s'.", "easy")

    def d_type():
        return bug(["void show() {", "  int count = 5;", "  print('Count: ' + count);", "}"], 2,
                   "String + int doesn't compile in Dart — use 'Count: $count' or count.toString().", "easy")

    def d_typo_type():
        return bug(["Strign name = 'Ram';", "print(name);"], 0,
                   "Typo: 'Strign' should be String.", "easy")

    def d_return():
        return bug(["class Box extends StatelessWidget {", "  Widget build(BuildContext context) {",
                    "    Text('hi');", "  }", "}"], 2,
                   "build() must RETURN the widget — add 'return' before Text(...).", "easy")

    def d_eq():
        v = random.choice([5, 10, 20])
        return bug(["void check(int n) {", f"  if (n = {v}) {{", "    print('ok');", "  }", "}"], 1,
                   "= assigns instead of comparing — Dart conditions need == and this won't compile for non-bool.", "medium")

    def d_async():
        return bug(["Future<int> load() async {", "  return 42;", "}", "void main() {", "  var x = load();",
                    "  print(x + 1);", "}"], 4,
                   "load() returns a Future — missing 'await' (and the caller needs async) before using the value.", "hard")

    def d_future_type():
        return bug(["void main() {", "  Future<String> name = fetchName();", "  print(name.length);", "}"], 2,
                   "name is a Future<String>, not a String — await it inside an async function first.", "hard")

    def d_list_typo():
        return bug(["List<Strign> names = ['a'];", "print(names);"], 0,
                   "Typo inside the generic — 'Strign' should be String.", "easy")

    def d_missing_brace():
        return bug(["void main() {", "  if (true) {", "    print('yes');", "}"], 2,
                   "Missing closing brace for the if-block before the function's brace — unbalanced braces.", "medium")

    pats += [d_setstate, d_await, d_index, d_paren, d_interp, d_type, d_typo_type, d_return,
             d_eq, d_async, d_future_type, d_list_typo, d_missing_brace]
    return pats


# ---------------- C/C++ pool (target 520) ----------------
def c_pool():
    pats = []
    pats += semis([
        ("int total = {v}", "printf(\"%d\", total);"),
        ("int {a} = {v}", "return {a};"),
        ("double rate = {v}.5", "printf(\"%f\", rate);"),
        ("int sum = {v} + {v}", "printf(\"%d\", sum);"),
    ], "Missing semicolon at the end of the statement — C requires it.", "easy")

    def c_include():
        return bug(["int main() {", "    printf(\"Hello\\n\");", "    return 0;", "}"], 0,
                   "printf is used but <stdio.h> was never included — implicit declaration warning/error.", "easy")

    def c_scanf_amp():
        v = random.choice([5, 10, 25])
        return bug(["int n;", f"scanf(\"%d\", n);", "printf(\"%d\", n);", "return 0;"], 1,
                   "scanf needs the ADDRESS of the variable — pass &n, otherwise it writes to garbage.", "hard")

    def c_eq():
        v = random.choice([0, 5, 10])
        return bug([f"int flag = {v};", f"if (flag = {v}) {{", "    printf(\"yes\");", "}"], 1,
                   "= assigns (always true for non-zero) instead of comparing — use ==.", "medium")

    def c_bitwise():
        return bug(["int a = 1, b = 2;", "if (a & b) {", "    printf(\"both\");", "}"], 1,
                   "& is bitwise AND — for logical AND use && (here 1 & 2 is 0, so 'both' never prints even if both true-ish).", "hard")

    def c_fmt():
        return bug(["float price = 9.99;", "printf(\"%d\", price);", "return 0;"], 1,
                   "Format mismatch — %d prints an int; a float needs %f (undefined behavior otherwise).", "medium")

    def c_offbyone():
        v = random.choice([3, 5, 10])
        return bug([f"int arr[{v}] = {{1, 2, 3}};", f"for (int i = 0; i <= {v}; i++)",
                    "    printf(\"%d\", arr[i]);", "return 0;"], 1,
                   f"i <= {v} reads arr[{v}] — one past the end (valid indexes stop at {v - 1}).", "medium")

    def c_break():
        return bug(["switch (x) {", "    case 1:", "        printf(\"one\");", "    case 2:",
                    "        printf(\"two\");", "}"], 2,
                   "Missing 'break;' after case 1 — execution falls through into case 2 as well.", "medium")

    def c_dangle():
        return bug(["int *p = malloc(sizeof(int));", "*p = 42;", "free(p);", "printf(\"%d\", *p);"], 3,
                   "Use after free — p is dangling; reading *p afterwards is undefined behavior.", "hard")

    def c_leak():
        return bug(["int *data = malloc(100 * sizeof(int));", "data[0] = 5;", "printf(\"%d\", data[0]);",
                    "return 0;"], 3,
                   "malloc'd memory is never freed — memory leak; call free(data) before returning.", "medium")

    def c_return():
        return bug(["int main() {", "    printf(\"hi\\n\");", "}"], 2,
                   "int main should return a value — add 'return 0;' (undefined behavior otherwise).", "easy")

    def c_strcmp():
        return bug(["char a[] = \"yes\";", "if (a == \"yes\") {", "    printf(\"match\");", "}"], 1,
                   "Comparing pointers, not contents — C strings must be compared with strcmp(a, \"yes\") == 0.", "hard")

    def c_extra_semi():
        return bug(["int i;", "int total = 0;", "for (i = 0; i < 5; i++);", "    total += i;",
                    "printf(\"%d\", total);"], 2,
                   "Stray semicolon after the for — the loop body is EMPTY; total += i runs once after the loop.", "hard")

    def c_while_assign():
        v = random.choice([5, 10])
        return bug([f"int x = {v};", f"while (x = {v}) {{", "    x--;", "}"], 1,
                   "= assigns, making the condition always true (non-zero) — infinite loop; use ==.", "hard")

    def c_cpp_std():
        return bug(["#include <iostream>", "int main() {", "    cout << \"Hello\";", "    return 0;", "}"], 2,
                   "'cout' is undeclared — the file is missing 'using namespace std;' (or use std::cout).", "easy")

    def c_cpp_delete():
        return bug(["int *arr = new int[10];", "arr[0] = 1;", "delete arr;"], 2,
                   "new[] needs delete[] — 'delete arr' on an array is undefined behavior.", "hard")

    def c_intdiv():
        v = random.choice([7, 9, 11])
        return bug([f"int total = {v};", "double half = total / 2;", "printf(\"%f\", half);"], 1,
                   "Integer division truncates BEFORE the double assignment — use total / 2.0.", "medium")

    def c_char_quote():
        return bug(["char c = \"a\";", "printf(\"%c\", c);"], 0,
                   "Double quotes make a string literal; a single char needs single quotes: 'a'.", "easy")

    pats += [c_include, c_scanf_amp, c_eq, c_bitwise, c_fmt, c_offbyone, c_break, c_dangle,
             c_leak, c_return, c_strcmp, c_extra_semi, c_while_assign, c_cpp_std,
             c_cpp_delete, c_intdiv, c_char_quote]
    return pats


# ---------------- YAML / Docker / CI pool (target 500) ----------------
def yaml_pool():
    svc = random.choice
    SERVICES = ["web", "api", "app", "frontend", "worker"]
    PORTS = [3000, 5000, 8000, 8080]

    def y_cmd_comma():
        return bug(["FROM node:18", "WORKDIR /app", "COPY package.json .", "RUN npm install", "EXPOSE 3000",
                    "CMD [\"node\" \"index.js\"]"], 5,
                   "Missing comma inside the CMD JSON array — should be [\"node\", \"index.js\"].", "easy")

    def y_ports():
        p = random.choice(PORTS)
        return bug(["version: '3'", "services:", "  web:", "    build: .", "    ports:",
                    f"      - '{p}-{p}'"], 5,
                   f"Port mapping uses a colon, not a hyphen — '{p}-{p}' should be '{p}:{p}' (host:container).", "easy")

    def y_pip():
        return bug(["FROM python:3.11", "COPY requirements.txt .", "RUN pip install requirements.txt"], 2,
                   "Missing the -r flag — 'pip install -r requirements.txt' installs FROM the file.", "easy")

    def y_on():
        return bug(["name: CI", "on push:", "jobs:", "  build:", "    runs-on: ubuntu-latest"], 1,
                   "YAML syntax error — the key/value split is 'on: push', not 'on push:'.", "easy")

    def y_dash():
        p = random.choice(PORTS)
        return bug(["services:", "  api:", "    image: nginx", "    ports:", f"      {p}:{p}"], 4,
                   f"List items in YAML need a leading dash — '- {p}:{p}'.", "easy")

    def y_colon_value():
        return bug(["config:", "  server:", "    port: 8000", "    time: 10:30"], 3,
                   "A value containing ': ' must be quoted — '10:30' breaks YAML parsing; use '10:30' in quotes or 1030.", "hard")

    def y_secret():
        return bug(["jobs:", "  deploy:", "    runs-on: ubuntu-latest", "    steps:",
                    "      - run: echo ${{ secrets.API_KEY }}"], 4,
                   "Echoing a secret to logs leaks it in CI output — secrets must never be printed.", "medium")

    def y_needs_case():
        return bug(["jobs:", "  Build:", "    runs-on: ubuntu-latest", "  deploy:",
                    "    needs: build"], 4,
                   "Job name is 'Build' (capital) but needs references 'build' — job ids are case-sensitive.", "hard")

    def y_runson():
        return bug(["jobs:", "  build:", "    runs-on: ubuntu_lastest"], 2,
                   "Typo in runner label — 'ubuntu_lastest' should be 'ubuntu-latest' (hyphen).", "easy")

    def y_from():
        return bug(["FORM node:18", "WORKDIR /app", "COPY . ."], 0,
                   "Dockerfiles start with FROM, not FORM — typo.", "easy")

    def y_copy():
        return bug(["FROM node:18", "COPY package.json", "RUN npm install"], 1,
                   "COPY needs a destination — COPY package.json . (source AND dest).", "easy")

    def y_workdir():
        return bug(["FROM node:18", "WORKDIR app", "COPY . ."], 1,
                   "WORKDIR should be an absolute path — '/app', not 'app'.", "medium")

    def y_kind():
        return bug(["apiVersion: apps/v1", "kind: Depoyment", "metadata:", "  name: web"], 1,
                   "Typo in kind — 'Depoyment' should be 'Deployment'.", "easy")

    def y_volume():
        return bug(["docker run -d \\", "  -v /data/app \\", "  nginx:alpine"], 1,
                   "Volume mappings need a colon between host and container paths: -v /data:/app.", "easy")

    def y_indent():
        return bug(["services:", "web:", "  image: nginx"], 1,
                   "'web' must be INDENTED under 'services:' — same indent makes it a sibling key, not a service.", "medium")

    def y_env():
        s = random.choice(SERVICES)
        return bug(["services:", f"  {s}:", "    environment:", "      MODE production"], 3,
                   "Environment items need 'KEY: value' — 'MODE production' misses the colon.", "easy")

    return [y_cmd_comma, y_ports, y_pip, y_on, y_dash, y_colon_value, y_secret, y_needs_case,
            y_runson, y_from, y_copy, y_workdir, y_kind, y_volume, y_indent, y_env]


# ---------------- Security pool (target 500) ----------------
def security_pool():
    def s_sqli():
        lang = random.choice(["js", "php", "py"])
        if lang == "js":
            return bug(["app.get('/user/:id', (req, res) => {",
                        "  db.query(`SELECT * FROM users WHERE id = ${req.params.id}`);",
                        "  res.send('ok');", "});"], 1,
                       "Template-literal SQL built from raw input — SQL injection; use parameterized queries.", "hard")
        if lang == "php":
            return bug(["$id = $_GET['id'];", "$q = \"SELECT * FROM users WHERE id = $id\";",
                        "mysqli_query($conn, $q);"], 1,
                       "GET input interpolated directly into SQL — SQL injection; use prepared statements.", "hard")
        return bug(["uid = request.args['id']", "q = f\"SELECT * FROM users WHERE id = {uid}\"",
                    "cur.execute(q)"], 1,
                   "f-string SQL with user input — SQL injection; pass parameters instead.", "hard")

    def s_plain():
        return bug(["user = User(username='ram', password='password123')", "user.save()"], 0,
                   "Password stored in plaintext — hash it first (set_password / bcrypt / argon2).", "medium")

    def s_md5():
        import hashlib
        algo = random.choice(["md5", "sha1"])
        return bug(["import hashlib", f"hashed = hashlib.{algo}(password.encode()).hexdigest()"], 1,
                   f"{algo.upper()} is fast and broken for password hashing — use bcrypt/argon2/PBKDF2.", "medium")

    def s_secret():
        return bug(["const jwt = require('jsonwebtoken');",
                    "const token = jwt.sign({ id }, 'mysecret123');"], 1,
                   "Hardcoded weak secret in source — load strong random secrets from environment variables.", "medium")

    def s_idor():
        return bug(["app.get('/user/:id', (req, res) => {", "  const user = db.getUser(req.params.id);",
                    "  res.json(user);", "});"], 0,
                   "No authentication/authorization check before returning user data — IDOR vulnerability.", "hard")

    def s_xss():
        kind = random.choice(["php", "js"])
        if kind == "php":
            return bug(["<input name='comment'>", "<?php echo $_POST['comment']; ?>"], 1,
                       "Echoing raw user input into HTML — XSS; escape with htmlspecialchars().", "medium")
        return bug(["const div = document.getElementById('out');",
                    "div.innerHTML = userInput;"], 1,
                   "Assigning raw input to innerHTML — XSS; use textContent or sanitize.", "medium")

    def s_eval():
        return bug(["function calc(input) {", "  return eval(input);", "}"], 1,
                   "eval() on user input executes arbitrary code — never use eval with untrusted data.", "hard")

    def s_token_url():
        return bug(["const url = 'https://api.example.com/data?token=' + jwt;", "fetch(url);"], 0,
                   "Tokens in URLs leak via logs/history/referrer — send them in the Authorization header.", "hard")

    def s_weak_random():
        return bug(["function makeToken() {", "  return Math.random().toString(36).slice(2);", "}"], 1,
                   "Math.random is not cryptographically secure — use crypto.randomUUID()/getRandomValues for tokens.", "medium")

    def s_http_login():
        return bug(["<form action='http://example.com/login' method='post'>", "  <input name='pass' type='password'>",
                    "</form>"], 0,
                   "Login form posts over plain http:// — credentials travel unencrypted; use https.", "easy")

    return [s_sqli, s_plain, s_md5, s_secret, s_idor, s_xss, s_eval, s_token_url, s_weak_random, s_http_login]


# ---------------- Marketing / Design / QA / GenAI / Pandas / SQL-bug pools ----------------
def steps_bug(steps, bugidx, note, diff, ctxs):
    def gen():
        ctx = {k: random.choice(v) for k, v in ctxs.items()}
        lines = [s.format(**ctx) for s in steps]
        return bug(lines, bugidx, note, diff)
    return gen


MKT_CTX = {"platform": ["Instagram", "Facebook", "TikTok", "LinkedIn", "YouTube"],
           "content": ["video", "reel", "blog post", "carousel", "story", "newsletter"],
           "audience": ["audience", "followers", "customers", "viewers", "subscribers"],
           "channel": ["email", "social", "search", "paid ads", "influencers"]}


def marketing_pool():
    T = []
    def mk(steps, idx, note, diff="medium"):
        T.append(steps_bug(steps, idx, note, diff, MKT_CTX))
    mk(["Step 1: Define the target {audience}", "Step 2: Set campaign goals with no measurable KPI",
        "Step 3: Choose channels and launch"], 1, "Goals without a measurable KPI can never be judged a success or failure.")
    mk(["Step 1: Set the monthly budget", "Step 2: Run the exact same creative for 6 months",
        "Step 3: Review metrics weekly"], 1, "Creative fatigue — audiences tune out; refresh creatives regularly.")
    mk(["Step 1: Import the full email list including unsubscribed users", "Step 2: Segment by interest",
        "Step 3: Send the campaign"], 0, "Emailing unsubscribed users breaks anti-spam laws (GDPR/CAN-SPAM).")
    mk(["Step 1: Promise 'guaranteed #1 ranking in 24 hours' in the {channel} headline",
        "Step 2: Launch the campaign"], 0, "Unverifiable guarantees break ad policies and destroy trust.")
    mk(["Step 1: Build a dedicated landing page", "Step 2: Send all {channel} traffic to the homepage instead",
        "Step 3: Measure conversion"], 1, "Targeted traffic sent to the generic homepage kills conversion; use the matching landing page.")
    mk(["Step 1: Post identical content at the same time on every {platform}",
        "Step 2: Use platform-specific hashtags"], 0, "Each platform's audience/format differs — tailor content per platform.")
    mk(["Step 1: Track engagement rate", "Step 2: Buy 10k fake {audience}",
        "Step 3: Analyze top formats"], 1, "Fake followers inflate vanity metrics, tank engagement rate and risk penalties.")
    mk(["Step 1: Schedule with a content calendar", "Step 2: Ignore all negative comments",
        "Step 3: Post 3-4x a week"], 1, "Ignoring negative comments erodes brand trust — respond professionally.")
    mk(["Step 1: Publish the {content} with no captions or subtitles",
        "Step 2: Share on every {platform}"], 0, "Most social {content} is watched muted — without captions the message is lost.")
    mk(["Step 1: Run a giveaway requiring 20 friend tags to enter", "Step 2: Announce the winner"], 0,
       "Tag-to-enter giveaways violate platform rules and attract disengaged followers.")
    mk(["Step 1: Research keywords", "Step 2: Repeat the keyword 30 times in the {content} for SEO",
        "Step 3: Add a CTA"], 1, "Keyword stuffing is penalized and unreadable — write naturally.")
    mk(["Step 1: Draft the {content}", "Step 2: Publish immediately without proofreading"], 1,
       "Skipping proofreading ships typos that hurt credibility.")
    mk(["Step 1: Study a competitor's hit {content}", "Step 2: Copy it and change a few words",
        "Step 3: Republish as yours"], 1, "Light-edit copying is plagiarism — legal and SEO penalties.")
    mk(["Step 1: Write the {content} with no meta description", "Step 2: Publish"], 0,
       "Missing meta description hurts click-through from search results.")
    mk(["Step 1: Build brand voice guidelines", "Step 2: Write every {content} in a generic voiceless tone"], 1,
       "No brand voice = forgettable content; consistency builds recognition.")
    mk(["Step 1: Plan 10 posts a day to maximize reach", "Step 2: Ignore analytics",
        "Step 3: Never review timing"], 0, "Spam-frequency posting plus ignoring analytics burns out the {audience}.")
    mk(["Step 1: Buy an email list of 50k addresses", "Step 2: Send the newsletter"], 0,
       "Purchased lists have no consent — bounces, spam traps and legal risk.")
    mk(["Step 1: Use a clickbait headline the {content} can't deliver", "Step 2: Promote it heavily"], 0,
       "Promise-mismatch clickbait destroys trust and triggers penalties.")
    mk(["Step 1: Design a beautiful {content}", "Step 2: Forget any call-to-action"], 1,
       "Without a CTA the {audience} has no next step — conversions die.")
    mk(["Step 1: Target everyone aged 18-65", "Step 2: Spend the full budget at once"], 0,
       "No audience segmentation = wasted spend; start narrow, then scale.")
    return T


DSN_CTX = {"medium": ["poster", "brochure", "banner", "flyer", "business card", "packaging"],
           "product": ["app", "website", "dashboard", "landing page", "checkout flow"]}


def design_pool():
    T = []
    def mk(steps, idx, note, diff="medium"):
        T.append(steps_bug(steps, idx, note, diff, DSN_CTX))
    mk(["Step 1: Set canvas to 72 DPI for the print {medium}", "Step 2: Design", "Step 3: Export CMYK"], 0,
       "Print needs at least 300 DPI — 72 DPI is for screens only.", "easy")
    mk(["Step 1: Design the {medium} in RGB for print", "Step 2: Convert to CMYK at the very end"], 0,
       "Design print in CMYK from the start — late conversion shifts colors.", "medium")
    mk(["Step 1: Pick the palette", "Step 2: Use 6 different fonts on the {medium}", "Step 3: Apply a grid"], 1,
       "Too many fonts break consistency — stick to 2-3.", "medium")
    mk(["Step 1: Export the logo only as JPEG", "Step 2: Deliver to client"], 0,
       "Logos need transparent scalable formats (SVG/PNG) — JPEG has a background and degrades.", "easy")
    mk(["Step 1: Use bright neon for all body text on the {medium}"], 0,
       "Neon body text is unreadable at length — use it sparingly as accent.", "easy")
    mk(["Step 1: Interview users", "Step 2: Skip wireframes, jump to hi-fi mockups",
        "Step 3: Test with users"], 1, "Skipping wireframes locks expensive decisions before flows are validated.", "easy")
    mk(["Step 1: Design 44x44px tap targets", "Step 2: Use icon-only navigation with no labels"], 1,
       "Icon-only nav hurts discoverability — add labels.", "medium")
    mk(["Step 1: Map the persona", "Step 2: Build a 12-step onboarding for the {product}"], 1,
       "12 steps is massive drop-off — shorten onboarding.", "hard")
    mk(["Step 1: Sketch 5 concepts", "Step 2: Pick idea #1 without comparing"], 1,
       "Committing without comparison skips exploration that finds better solutions.", "easy")
    mk(["Step 1: Design the {product} error states", "Step 2: Show one generic 'Something went wrong' for every failure"], 1,
       "Generic errors don't tell users how to fix the problem.", "hard")
    mk(["Step 1: Style the {product} card", "Step 2: Use #cccccc text on white"], 1,
       "Light gray on white fails WCAG contrast.", "easy")
    mk(["Step 1: Build the mobile nav", "Step 2: Give links 2px padding"], 1,
       "Tap targets under ~44x44px are hard to hit.", "medium")
    mk(["Step 1: Use placeholder text as the only label in the form"], 0,
       "Placeholders vanish while typing — keep a real label.", "medium")
    mk(["Step 1: Add an icon button with no alt/aria-label"], 0,
       "No accessible name — screen reader users can't tell what it does.", "easy")
    mk(["Step 1: Make account deletion a single tap"], 0,
       "Destructive action needs a confirmation step.", "easy")
    mk(["Step 1: Show a spinner on submit", "Step 2: Never dismiss it on failure"], 1,
       "A spinner that never clears traps users — surface errors.", "medium")
    mk(["Step 1: Typeset the {medium}", "Step 2: Set body copy at 10px for style"], 1,
       "10px body text fails readability — keep >= ~14px equivalent.", "easy")
    mk(["Step 1: Lay out the {medium} freely", "Step 2: Use no grid or spacing system"], 1,
       "No grid = inconsistent alignment and spacing.", "medium")
    return T


def qa_pool():
    def q_eq():
        v = random.choice([5, 200, 201])
        return bug(["def test_create():", f"    result = create({v})", f"    assert result = {v}"], 2,
                   "= assigns inside assert — must be ==.", "easy")
    def q_status():
        return bug(["def test_login():", "    r = login('user', 'wrongpass')", "    assert r.status_code == 200"], 2,
                   "A failed login should expect 401/403 — asserting 200 makes the test wrong.", "medium")
    def q_expected():
        return bug(["Test Case: checkout button", "Step 1: Add item", "Step 2: Click checkout",
                    "Expected Result: (not specified)"], 3,
                   "A test case without an expected result can't be verified.", "hard")
    def q_happy():
        return bug(["Plan: test only the happy path with valid data", "Skip boundary and invalid inputs",
                    "Mark fully tested when happy path passes"], 2,
                   "'Fully tested' after happy-path only is misleading — boundaries and negatives are required.", "hard")
    def q_sleep():
        return bug(["def test_sync():", "    start_sync()", "    time.sleep(30)", "    assert done"], 2,
                   "Fixed sleeps make tests slow and flaky — poll for the condition instead.", "medium")
    def q_prod():
        return bug(["# smoke test plan", "1. Run load test against the production database"], 1,
                   "Load-testing production can take the real service down — use staging.", "hard")
    def q_teardown():
        return bug(["def test_upload():", "    create_test_files('/tmp/f')", "    assert upload('/tmp/f')"], 0,
                   "No teardown/cleanup — test files accumulate and poison later runs.", "medium")
    def q_dup():
        return bug(["def test_search():", "    assert search('x')", "def test_search():",
                    "    assert search('y')"], 2,
                   "Duplicate test names — the second definition shadows the first (one test silently never runs).", "hard")
    return [q_eq, q_status, q_expected, q_happy, q_sleep, q_prod, q_teardown, q_dup]


def genai_pool():
    def g_comma():
        return bug(["import openai", "response = openai.ChatCompletion.create(", "  model='gpt-4'",
                    "  messages=[{'role': 'user', 'content': 'Hi'}]", ")"], 2,
                   "Missing comma after model='gpt-4' — SyntaxError.", "easy")
    def g_fstring():
        return bug(["def build_prompt(topic):", "    return f'Write about {topics}'"], 1,
                   "f-string references 'topics' (undefined) — the parameter is 'topic'.", "medium")
    def g_typo():
        return bug(["prompt = \"Summarize: \" + text", "response = model.generate(propmt)"], 1,
                   "'propmt' is a typo of 'prompt' — NameError.", "easy")
    def g_loop_var():
        return bug(["for doc in documents:", "    embedding = model.encode(doc)", "    embeddings.append(embedding)",
                    "matrix = np.array(embedding)"], 3,
                   "Uses the LAST loop variable instead of the accumulated 'embeddings' list.", "hard")
    def g_norm():
        return bug(["import numpy as np", "def cosine(a, b):", "    return np.dot(a, b) / (np.norm(a) * np.norm(b))"], 2,
                   "np.norm doesn't exist — it's np.linalg.norm.", "medium")
    def g_global():
        return bug(["chat_history = []", "def chat(msg):", "    chat_history = chat_history + [msg]",
                    "    return model.generate(chat_history)"], 2,
                   "Reassigning before reading raises UnboundLocalError — declare global or use append().", "hard")
    def g_model():
        return bug(["response = client.chat.completions.create(", "  model='gpt4',", "  messages=msgs", ")"], 1,
                   "Model id typo — 'gpt4' is invalid; ids look like 'gpt-4' / 'gpt-4o'.", "easy")
    def g_temp():
        return bug(["response = client.chat.completions.create(", "  model='gpt-4',",
                    "  temperature='medium',", "  messages=msgs", ")"], 2,
                   "temperature is a NUMBER (0-2), not a string.", "easy")
    def g_key():
        return bug(["client = OpenAI(api_key='sk-proj-abc123def456')"], 0,
                   "API key hardcoded in source — load from environment variable and rotate the leaked key.", "hard")
    return [g_comma, g_fstring, g_typo, g_loop_var, g_norm, g_global, g_model, g_temp, g_key]


def pandas_pool():
    def pd_shape():
        return bug(["import pandas as pd", "df = pd.DataFrame(data)", "print(df.shape())"], 2,
                   "df.shape is a property, not a method — drop the ().", "easy")
    def pd_eq():
        return bug(["import pandas as pd", "df = pd.read_csv('data.csv')", "adults = df[df['age'] = 25]"], 2,
                   "= assigns inside the filter — use ==.", "medium")
    def pd_paren():
        return bug(["import pandas as pd", "df = pd.read_csv('data.csv')", "print(df.head()"], 2,
                   "Missing closing parenthesis on df.head().", "easy")
    def pd_sort():
        return bug(["sales = df.groupby('region')['sales'].sum()", "top = sales.sort_values().head(3)"], 1,
                   "sort_values() defaults to ASCENDING — head() then returns the LOWEST; use ascending=False.", "hard")
    def pd_dropna():
        return bug(["df = pd.read_csv('data.csv')", "df.dropna()", "df.to_csv('clean.csv')"], 1,
                   "dropna() returns a NEW frame — without inplace=True or reassignment, nothing is dropped.", "medium")
    def pd_file():
        return bug(["import pandas as pd", "df = pd.read_csv('data.csx')"], 1,
                   "File typo — 'data.csx' should be 'data.csv' (FileNotFoundError).", "easy")
    def pd_plt():
        return bug(["import matplotlib.pyplot as plt", "data = [10, 20, 30]",
                    "plt.bar(range(len(data), data)", "plt.show()"], 2,
                   "Parenthesis mismatch — range(len(data) never closes before the comma.", "medium")
    def pd_json():
        return bug(["import json", "cfg = json.load('{\"debug\": true}')"], 1,
                   "A JSON *string* needs json.loads(); json.load() is for file objects.", "medium")
    def pd_loc():
        return bug(["df = pd.DataFrame({'a': [1, 2, 3]})", "print(df.loc[2])"], 0,
                   "Unbalanced parenthesis in the DataFrame constructor — missing ')' before the second line.", "easy")
    return [pd_shape, pd_eq, pd_paren, pd_sort, pd_dropna, pd_file, pd_plt, pd_json, pd_loc]


def sqlbug_pool():
    def sb_group():
        t = random.choice(["employees", "orders", "products"])
        return bug([f"SELECT category, COUNT(*) FROM {t}", "GROUP category;"], 1,
                   "Missing BY — it must be GROUP BY category.", "easy")
    def sb_comma():
        return bug(["SELECT name price FROM products;"], 0,
                   "Missing comma between columns — 'name price' parses as 'name AS price'.", "easy")
    def sb_null():
        return bug(["SELECT * FROM products", "WHERE category = NULL;"], 1,
                   "= NULL never matches — NULL comparisons need IS NULL.", "medium")
    def sb_like():
        return bug(["SELECT * FROM users", "WHERE name LIKE 'A';"], 1,
                   "LIKE 'A' matches only exactly 'A' — a starts-with search needs 'A%'.", "easy")
    def sb_delete():
        return bug(["-- goal: remove only cancelled test rows", "DELETE FROM orders;"], 1,
                   "DELETE without WHERE wipes the whole table.", "hard")
    def sb_quote():
        return bug(["SELECT * FROM users", "WHERE city = Kathmandu;"], 1,
                   "String literal needs quotes — 'Kathmandu' (else it's an unknown column).", "easy")
    def sb_join():
        return bug(["SELECT c.name, o.total", "FROM customers c JOIN orders o;", "WHERE c.id = o.customer_id;"], 1,
                   "JOIN has no ON condition — without ON it becomes a full cross join before the WHERE.", "hard")
    def sb_count():
        return bug(["SELECT COUNT(name), FROM users;"], 0,
                   "Stray comma before FROM — invalid syntax.", "easy")
    return [sb_group, sb_comma, sb_null, sb_like, sb_delete, sb_quote, sb_join, sb_count]


# ============================================================
# 4b) PARAMETRIZED VERSIONS — wide parameter spaces (override the
#     fixed pools above; Python uses the last definition at call time)
# ============================================================

RC = random.choice


def htmlcss_pool():
    TAGS = [("ul", "li"), ("div", "p"), ("span", "b"), ("form", "div"),
            ("nav", "a"), ("section", "article"), ("table", "tr"), ("details", "summary")]
    CLS = ["box", "card", "header", "menu", "panel", "widget", "item", "badge", "toast", "modal"]
    ICONS = ["delete.png", "edit.png", "close.png", "menu.png", "save.png", "search.png"]
    FIELDS = [("Email", "email", "user-email"), ("Name", "text", "user-name"),
              ("Phone", "tel", "user-phone"), ("Address", "text", "user-address"),
              ("Password", "password", "user-pass"), ("Age", "number", "user-age")]
    PROPS = [("color", "colr"), ("border", "bortder"), ("font-size", "fon-size"),
             ("background", "bakground"), ("width", "widht"), ("height", "heigth"),
             ("margin", "margn"), ("padding", "pading"), ("display", "disply"),
             ("overflow", "overflw")]
    BGS = ["#1e293b", "#0f172a", "#111827", "#18122b"]
    DIMS = ["100", "50", "320", "640", "16", "48", "240", "80"]
    UNITS = ["px", "%", "rem", "vw"]
    ELIDS = ["header", "footer", "sidebar", "navbar", "banner", "toolbar", "drawer", "hero"]

    def h_close():
        o, i = RC(TAGS); c = RC(CLS)
        return bug([f"<{o} class='{c}'>", f"  <{i}>Text</{i}>", f"<{i}>"], 2,
                   f"Closing tag mismatch — the outer <{o}> must be closed with </{o}>, not another <{i}>.", "easy")

    def h_alt():
        return bug(["<button style='width:16px;height:16px'>", f"  <img src='{RC(ICONS)}'>", "</button>"], 1,
                   "Icon image has no alt text or aria-label — screen reader users can't tell what the button does.", "easy")

    def h_label():
        lbl, typ, iid = RC(FIELDS)
        return bug(["<form>", f"  <label>{lbl}</label>", f"  <input type='{typ}' id='{iid}'>", "</form>"], 1,
                   f"The label isn't linked — add for='{iid}' matching the input's id.", "medium")

    def h_dup():
        iid = RC(ELIDS)
        return bug([f"<nav id='{iid}'>", f"<div id='{iid}'>"], 1,
                   f"Duplicate id '{iid}' — ids must be unique; scripts and labels bind only to the first.", "medium")

    def h_quote():
        pg = RC(["index.html", "about us.html", "contact page.html", "my docs.html"])
        return bug([f"<a href={pg}>Home</a>"], 0,
                   "Attribute value must be quoted — unquoted values break as soon as they contain spaces.", "easy")

    def c_typo():
        p, b = RC(PROPS); c = RC(CLS)
        return bug([f".{c} {{", f"  {b}: red;", "  padding: 10px;", "}"], 1,
                   f"CSS typo — '{b}' is not a property; the browser ignores it. It should be '{p}'.", "easy")

    def c_semi():
        c = RC(CLS); bg = RC(BGS)
        return bug([f".{c} {{", "  color: #ffffff", f"  background: {bg};", "}"], 1,
                   "Missing semicolon — the following declaration gets swallowed into an invalid one.", "easy")

    def c_colon():
        c = RC(CLS)
        return bug([f".{c} {{", "  color #ffffff;", "}"], 1,
                   "Missing colon between property and value — invalid declaration.", "easy")

    def c_val():
        c = RC(CLS); p, _ = RC(PROPS)
        return bug([f".{c} {{", f"  {p}: 15px;", "}"], 1,
                   f"Wrong value type for '{p}' — it doesn't accept a length like 15px.", "easy")

    def c_unit():
        c = RC(CLS); d = RC(DIMS); u = RC(UNITS)
        return bug([f".{c} {{", f"  width: {d};", "}"], 1,
                   f"Length missing its unit — should be {d}{u} (only 0 may be unitless).", "easy")

    def c_sel():
        iid = RC(ELIDS)
        return bug([f"<div id='{iid}'></div>", "<style>", f"  .{iid} {{ color: red; }}", "</style>"], 2,
                   f"The element has id='{iid}' but the CSS targets a class — the selector must be #{iid}.", "medium")

    def c_flex():
        c = RC(CLS)
        return bug([f".{c} {{", "  display: block;", "  justify-content: space-between;", "}"], 1,
                   "justify-content only works in flex/grid containers — display must be flex or grid.", "medium")

    return [h_close, h_alt, h_label, h_dup, h_quote, c_typo, c_semi, c_colon, c_val, c_unit, c_sel, c_flex]


def node_pool():
    ROUTES = ["/api/users", "/api/items", "/api/orders", "/api/posts", "/api/products",
              "/api/tasks", "/api/notes", "/api/reports"]
    MODELS = [("User", "users"), ("Item", "items"), ("Order", "orders"), ("Post", "posts"),
              ("Product", "products"), ("Task", "tasks"), ("Note", "notes")]
    FLD = ["name", "email", "title", "price", "status", "qty"]
    PORTS = [3000, 4000, 5000, 8000]

    def n_start():
        return bug(["const express = require('express');", "const app = express();",
                    f"app.get('/', (req, res) => res.send('hi'));", f"app.start({RC(PORTS)});"], 3,
                   "There is no app.start() — Express listens with app.listen(port).", "easy")

    def n_await_save():
        M, _ = RC(MODELS)
        return bug([f"router.post('{RC(ROUTES)}', async (req, res) => {{", f"  const doc = new {M}(req.body);",
                    "  doc.save();", "  res.json(doc);", "});"], 2,
                   "Missing 'await' before doc.save() — the response is sent before the document is saved and save errors are lost.", "medium")

    def n_comma():
        r1, r2 = RC(ROUTES), RC(ROUTES)
        return bug([f"app.get('{r1}', (req, res) => {{", "  res.json(all);", "});",
                    f"app.post('{r2}' (req, res) => {{", "  all.push(req.body);", "});"], 3,
                   "Missing comma between the route path and the handler in app.post().", "easy")

    def n_model():
        M, _ = RC(MODELS)
        return bug([f"const {M.lower()}Schema = new mongoose.Schema({{ total: Number }});",
                    f"const {M} = mongoose.Model('{M}', {M.lower()}Schema);"], 1,
                   "mongoose.Model is not the model factory — use lowercase mongoose.model().", "medium")

    def n_mw_order():
        return bug(["const app = express();", f"app.post('{RC(ROUTES)}', (req, res) => res.json({{}}));",
                    "app.use(cors());"], 2,
                   "cors() middleware is registered AFTER the route, so it never applies to it — middleware must come first.", "hard")

    def n_body():
        return bug(["const app = express();", f"app.post('{RC(ROUTES)}', (req, res) => {{",
                    f"  console.log(req.body.{RC(FLD)});", "});"], 2,
                   "req.body is undefined — the express.json() body-parser middleware was never registered.", "medium")

    def n_await_find():
        M, _ = RC(MODELS)
        return bug([f"app.get('{RC(ROUTES)}', async (req, res) => {{", f"  const docs = {M}.find();",
                    "  res.json(docs);", "});"], 1,
                   "Missing 'await' — find() returns a Query/Promise, not documents.", "medium")

    def n_sent():
        return bug([f"app.get('{RC(ROUTES)}', (req, res) => {{", "  res.send('moved');",
                    "  res.redirect('/new');", "});"], 2,
                   "Headers were already sent by res.send() — you cannot redirect afterwards.", "hard")

    def n_var():
        a, b = RC([("users", "user"), ("items", "item"), ("orders", "order"),
                   ("posts", "post"), ("tasks", "task")])
        return bug([f"const {a} = load{a.capitalize()}();", f"res.json({b});"], 1,
                   f"Variable mismatch — '{b}' is undefined; the data lives in '{a}'.", "easy")

    def n_next():
        return bug(["app.use((req, res, next) => {", "  console.log(req.url);", "});"], 1,
                   "Custom middleware never calls next() — every request hangs; nothing after it runs.", "hard")

    def n_hang():
        return bug([f"app.get('{RC(ROUTES)}', (req, res) => {{", f"  const docs = await {RC(MODELS)[0]}.find();",
                    "});"], 2,
                   "The handler never responds — without res.send()/res.json() the request hangs until timeout.", "medium")

    def n_catch():
        return bug([f"app.get('{RC(ROUTES)}', async (req, res) => {{",
                    "  const data = await fetchData();", "});"], 1,
                   "No try/catch around the await — a rejection becomes an unhandled rejection instead of a 500 response.", "medium")

    return [n_start, n_await_save, n_comma, n_model, n_mw_order, n_body, n_await_find,
            n_sent, n_var, n_next, n_hang, n_catch]


def react_pool():
    STATES = [("count", "setCount"), ("total", "setTotal"), ("name", "setName"),
              ("items", "setItems"), ("score", "setScore"), ("qty", "setQty")]
    HND = ["handleClick", "handleSave", "handleSubmit", "handleDelete", "handleToggle", "handleReset"]
    PROP = ["user", "profile", "post", "order", "product", "comment"]
    FLD = ["name", "email", "price", "title", "label", "id"]
    COMP = ["App", "Panel", "Widget", "Form", "List", "Card"]

    def r_key():
        f = RC(FLD); c = RC(COMP)
        return bug([f"function {c}({{ rows }}) {{", "  return (", "    <ul>",
                    f"      {{rows.map(r => <li>{{r.{f}}}</li>)}}", "    </ul>", "  ); }"], 3,
                   "Missing 'key' prop when rendering a list — React needs a stable unique key per mapped item.", "easy")

    def r_call():
        h = RC(HND)
        return bug(["function App() {", f"  function {h}() {{ console.log('x'); }}",
                    f"  return <button onClick={{{h}()}}>Go</button>;", "}"], 2,
                   f"onClick={{{h}()}} invokes the function during render — pass the reference: onClick={{{h}}}.", "medium")

    def r_deps():
        s, ss = RC(STATES)
        return bug(["function Counter() {", f"  const [{s}, {ss}] = useState(0);",
                    f"  useEffect(() => {{ {ss}({s} + 1); }});", "  return <div>{s}</div>; }"], 2,
                   "useEffect has no dependency array — it runs after EVERY render, creating an infinite update loop.", "hard")

    def r_mutate():
        _, ss = RC(STATES)
        return bug(["function add(item) {", "  items.push(item);", f"  {ss}(items);", "}"], 1,
                   "Mutating state directly — React compares references so it may never re-render; build a new array.", "hard")

    def r_typo():
        _, ss = RC(STATES)
        wrong = ss[:-2] + ss[-1] + ss[-2]
        return bug(["function Counter() {", f"  const [n, {ss}] = useState(0);",
                    f"  return <button onClick={{() => {wrong}(n + 1)}}>+1</button>;", "}"], 2,
                   f"Typo: {wrong} is not defined — the setter from useState is {ss}.", "easy")

    def r_import():
        h = RC(["useState", "useEffect"])
        return bug([f"function {RC(COMP)}() {{", f"  const [n, setN] = {h}(0);",
                    "  return <div>{n}</div>; }"], 1,
                   f"{h} is used but never imported from 'react' — ReferenceError.", "easy")

    def r_this():
        f = RC(FLD)
        return bug([f"function Card(props) {{", f"  return <div>{{this.props.{f}}}</div>;", "}"], 1,
                   f"Functional components have no 'this' — use props.{f} directly.", "medium")

    def r_guard():
        p = RC(PROP)
        return bug([f"function View({{ {p} }}) {{", f"  return <div>{{{p}.{RC(FLD)}}}</div>;", "}"], 1,
                   f"{p} is undefined while loading — accessing a field crashes; guard with {p}?.field.", "medium")

    def r_ret():
        f = RC(FLD)
        return bug(["function List({ rows }) {", "  return (", "    <div>",
                    f"      {{rows.map(r => {{ r.{f} }})}}", "    </div>", "  ); }"], 3,
                   "Curly-arrow body needs an explicit return — the expression is computed and discarded.", "hard")

    def r_stale():
        s, ss = RC(STATES)
        return bug(["function Timer() {", f"  const [{s}, {ss}] = useState(0);", "  useEffect(() => {",
                    f"    const id = setInterval(() => {ss}({s} + 1), 1000);", "    return () => clearInterval(id);",
                    "  }, []);", "  return <div>{s}</div>; }"], 3,
                   "Stale closure — the value is captured once; use the functional update set(x => x + 1).", "hard")

    def r_bool():
        s, _ = RC(STATES)
        return bug([f"function Badge() {{", f"  const [{s}] = useState(0);",
                    f"  return <div>{{{s} && <span>Online</span>}}</div>; }}"], 2,
                   "Rendering number && JSX prints a literal 0 when the value is 0 — check > 0 or use a boolean.", "medium")

    def r_input():
        return bug([f"function {RC(COMP)}() {{", f"  const [name, setName] = useState('');",
                    "  return <input value={name} />", "}"], 2,
                   "Controlled input with value but no onChange — React makes it read-only; add onChange={e => setName(e.target.value)}.", "medium")

    return [r_key, r_call, r_deps, r_mutate, r_typo, r_import, r_this, r_guard, r_ret,
            r_stale, r_bool, r_input]


def next_pool():
    ROUTES = ["/about", "/dashboard", "/profile", "/blog", "/shop", "/docs", "/team", "/pricing"]
    INIT = [(0, "+ 1"), ("", "+ '!'"), ("[]", ".concat([1])")]

    def x_link():
        r = RC(ROUTES)
        return bug(["import Link from 'next/link';", "export default function Nav() {",
                    f"  return <Link href='{r}'>Go<Link>;", "}"], 2,
                   "Closing tag must be </Link>, not another opening <Link>.", "easy")

    def x_state():
        i, op = RC(INIT)
        return bug(["'use client'", "import { useState } from 'react';",
                    "export default function Counter() {", "  const [n, setN] = useState();",
                    f"  return <button onClick={{() => setN(n {op})}}>{{n}}</button>; }}"], 3,
                   "useState() has no initial value — n starts undefined and updates produce NaN/undefined.", "medium")

    def x_await():
        return bug(["export async function getServerSideProps() {",
                    f"  const res = fetch('https://api.example.com{RC(ROUTES)}');",
                    "  const data = res.json();", "  return { props: { data } }; }"], 1,
                   "Missing 'await' before fetch() — res is a pending Promise and res.json() fails.", "hard")

    def x_client():
        return bug(["import { useState } from 'react';", "export default function Counter() {",
                    "  const [n, setN] = useState(0);",
                    "  return <button onClick={() => setN(n + 1)}>{n}</button>; }"], 0,
                   "useState/onClick need client interactivity — the file is missing the 'use client' directive at the top.", "hard")

    def x_key():
        return bug(["export default function Tags({ tags }) {", "  return (", "    <div>",
                    "      {tags.map(t => <span key={'x'}>{t}</span>)}", "    </div>", "  ); }"], 3,
                   "Hardcoded non-unique key ('x') on every item — keys must be unique per item.", "medium")

    def x_param():
        return bug(["export function generateStaticParams() {", f"  return fetch('/api{RC(ROUTES)}'); }}"], 1,
                   "generateStaticParams must return an array of param objects, not a raw fetch Response.", "medium")

    return [x_link, x_state, x_await, x_client, x_key, x_param]


def php_pool():
    VARS = ["name", "total", "count", "user", "email", "qty", "price", "msg"]
    STRS = ["hello", "done", "saved", "ok", "sent", "loaded"]
    NUMS = [5, 10, 20, 50, 100]

    def pp_dollar():
        a = RC(VARS)
        return bug([f"${a} = '{RC(STRS)}';", f"echo {a};"], 1,
                   f"PHP variables need the $ prefix — '{a}' without $ is an undefined constant.", "easy")

    def pp_semi():
        a = RC(VARS)
        return bug([f"${a} = {RC(NUMS)}", f"echo ${a};"], 0,
                   "Missing semicolon at the end of the assignment statement.", "easy")

    def pp_assign():
        v = RC(NUMS)
        return bug([f"$level = {v};", f"if ($level = {v}) {{", "  echo 'ten';", "}"], 1,
                   "= assigns instead of comparing — use == or ===.", "medium")

    def pp_concat():
        return bug([f"$name = '{RC(['Ram', 'Sita', 'Hari', 'Gita'])}';", "echo 'Hello ' + $name;"], 1,
                   "PHP concatenation uses the dot (.), not + — '+' converts strings to numbers.", "easy")

    def pp_quote():
        return bug([f"echo '{RC(STRS)};"], 0,
                   "Missing closing quote — unterminated string literal (parse error).", "easy")

    def pp_array():
        k1, k2 = RC(["debug", "log", "cache", "strict", "trace"]), RC(["mode", "level", "ttl", "pool", "file"])
        return bug(["$cfg = array(", f"  '{k1}' => true", f"  '{k2}' => false", ");"], 1,
                   "Missing comma between array items — PHP parse error.", "easy")

    def pp_typo():
        return bug([f"$msg = '{RC(STRS)}';", f"eco $msg;"], 1,
                   "Typo: 'eco' should be 'echo'.", "easy")

    def pp_header():
        return bug([f"echo '{RC(['Starting...', 'Loading...', 'Header sent...'])}';",
                    "header('Location: /home');"], 1,
                   "header() must run BEFORE any output — the echo already sent headers.", "hard")

    def pp_interp():
        a = RC(VARS)
        return bug([f"${a} = ['k' => 'v'];", f"echo \"Value ${a}['k']\";"], 1,
                   "Array access inside double quotes needs braces — use {$var['k']}; the parser can't read $var['k'].", "medium")

    def pp_foreach():
        return bug(["$items = [1, 2, 3];", "foreache ($items as $item) {", "  echo $item;", "}"], 1,
                   "Typo: 'foreache' should be 'foreach'.", "easy")

    def pp_isset():
        return bug([f"if (isset(${RC(VARS)})) {{", f"  echo ${RC(VARS)};", "} else {",
                    "  echo isst($x);", "}"], 3,
                   "Typo: 'isst' should be 'isset'.", "easy")

    def pp_sql():
        return bug([f"$sql = \"SELECT * FROM users WHERE name = '${RC(VARS)}'\";",
                    "$res = mysqli_query($conn, $sql);"], 0,
                   "User input concatenated straight into SQL — SQL injection; use prepared statements.", "hard")

    return [pp_dollar, pp_semi, pp_assign, pp_concat, pp_quote, pp_array, pp_typo,
            pp_header, pp_interp, pp_foreach, pp_isset, pp_sql]


def laravel_pool():
    MODELS = [("Post", "posts"), ("User", "users"), ("Order", "orders"), ("Product", "products"),
              ("Task", "tasks"), ("Invoice", "invoices")]
    COLS = ["title", "name", "total", "price", "status", "email"]

    def l_semi():
        return bug(["Route::get('/home', function () {", "    return view('home')", "});"], 1,
                   "Missing semicolon after return view('home').", "easy")

    def l_where():
        return bug(["public function search($q) {",
                    f"    return {RC(MODELS)[0]}::where('{RC(COLS)}', 'LIKE' \"%$q%\")->get();", "}"], 1,
                   "Missing comma between 'LIKE' and the search pattern — the where() call breaks.", "medium")

    def l_fillable():
        c1, c2 = RC(COLS), RC(COLS)
        return bug(["class Post extends Model {", f"    protected $fillable = ['{c1}', '{c2}']", "}"], 1,
                   "Missing semicolon after the $fillable array.", "easy")

    def l_var():
        a = RC(MODELS)[1]
        single = a[:-1] if a.endswith("s") else a
        return bug(["public function index() {", f"    ${a} = {single.capitalize()}::all();",
                    f"    return view('{a}.index', ['{a}' => ${single}]);", "}"], 2,
                   f"Variable mismatch — the view receives ${single} which was never defined (data is in ${a}).", "medium")

    def l_order():
        return bug(["Route::get('/posts/{id}', [PostController::class, 'show']);",
                    "Route::get('/posts/create', [PostController::class, 'create']);"], 0,
                   "The wildcard '/posts/{id}' is registered BEFORE '/posts/create' — 'create' is swallowed as an id.", "hard")

    def l_all():
        M, t = RC(MODELS)
        return bug(["public function index() {", f"    $data = {M}::all;",
                    f"    return view('{t}', compact('data'));", "}"], 1,
                   f"{M}::all is missing parentheses — it passes the method itself, not results.", "easy")

    def l_compact():
        a = RC(MODELS)[1]
        single = a[:-1] if a.endswith("s") else a
        return bug(["public function index() {", f"    ${a} = {single.capitalize()}::all();",
                    f"    return view('{a}', compact('{single}'));", "}"], 2,
                   f"compact('{single}') references ${single} — the variable is actually ${a}.", "medium")

    return [l_semi, l_where, l_fillable, l_var, l_order, l_all, l_compact]


def django_pool():
    MODELS = [("Post", "posts"), ("Product", "products"), ("Order", "orders"), ("Student", "students")]
    VIEWS = ["index", "detail", "list_view", "dashboard"]

    def dj_render():
        v = RC(VIEWS)
        return bug(["from django.shortcuts import render", "", f"def {v}(request):",
                    "    return render('home.html')"], 3,
                   "render() needs the request first: render(request, 'home.html') — TypeError otherwise.", "easy")

    def dj_all():
        M, t = RC(MODELS)
        return bug([f"def list_{t}(request):", f"    data = {M}.objects.all",
                    f"    return render(request, 'list.html', {{'data': data}})"], 1,
                   f"{M}.objects.all is missing () — it passes the method itself, not the queryset.", "easy")

    def dj_valid():
        return bug(["def register(request):", "    form = RegisterForm(request.POST)",
                    "    if form.is_valid:", "        form.save()"], 2,
                   "is_valid is a method — without () the condition is always truthy.", "medium")

    def dj_filter():
        M = RC(MODELS)[0]
        return bug(["def view(request):", f"    data = {M}.objects.filter(price > 100)",
                    "    return render(request, 'p.html', {'data': data})"], 1,
                   "Django filters need field__gt=100 lookup syntax, not Python operators.", "medium")

    def dj_path():
        v = RC(VIEWS)
        return bug(["urlpatterns = [",
                    f"    path('{RC(['posts/', 'items/', 'users/'])}', views.{v}, name='{v}')", "]"], 1,
                   "Missing comma after the path() entry — breaks the urlpatterns list.", "easy")

    def dj_delete():
        return bug(["def remove(request, id):", "    order = Order.objects.get(id=id)", "    order.delete",
                    "    return redirect('orders')"], 2,
                   "order.delete is a method reference without () — the row is never deleted.", "medium")

    def dj_maxdigit():
        return bug(["class Product(models.Model):",
                    "    price = models.DecimalField(max_digit=10, decimal_places=2)"], 1,
                   "Typo — it must be max_digits (plural).", "easy")

    return [dj_render, dj_all, dj_valid, dj_filter, dj_path, dj_delete, dj_maxdigit]


def wp_pool():
    SLUGS = ["greet", "box", "cta", "badge", "panel", "banner", "ticker", "grid"]

    def w_hook():
        return bug(["function my_scripts() {", "    wp_enqueue_style('main', get_stylesheet_uri());", "}",
                    "add_action('wp_enqueue_script', 'my_scripts');"], 3,
                   "Wrong hook name — it must be 'wp_enqueue_scripts' (plural).", "easy")

    def w_shortcode():
        s = RC(SLUGS)
        return bug(["function run($atts) {", "    return 'Hello';", "}",
                    f"add_shortcode('{s}' '{s}');"], 3,
                   "Missing comma between the shortcode tag and the callback name.", "easy")

    def w_args():
        k = RC(["post_type", "category", "author", "tag"])
        return bug(["$args = array(", f"    '{k}' => 'post'", "    'posts_per_page' => 5", ");",
                    "$q = new WP_Query($args);"], 1,
                   "Missing comma between the array items.", "easy")

    def w_theme():
        return bug(["function setup() {", "    add_theme_support('post-thumbnails')", "}",
                    "add_action('after_setup_theme', 'setup');"], 1,
                   "Missing semicolon after add_theme_support(...).", "easy")

    def w_loop():
        return bug(["<?php if (have_posts()) : ?>", "  <?php while (have_posts()) : the_post(); ?>",
                    "    <h2><?php the_title(); ?></h2>", "<?php endwhile; ?>"], 3,
                   "The loop closes with endwhile but the outer if never gets its endif;.", "medium")

    def w_header():
        return bug(["getheader();", "while (have_posts()) {", "  the_post();", "}"], 0,
                   "Typo: 'getheader' should be 'get_header'.", "easy")

    def w_haveposts():
        return bug(["<?php if (have_posts) : ?>", "  <?php the_post(); ?>", "<?php endif; ?>"], 0,
                   "have_posts is a function — it needs parentheses: have_posts().", "medium")

    def w_enqueue():
        h = RC(["main", "theme", "app", "style"])
        return bug(["function my_scripts() {",
                    f"    wp_enqueue_style('{h}', get_stylesheet_uri())", "}",
                    "add_action('wp_enqueue_scripts', 'my_scripts');"], 1,
                   "Missing semicolon after wp_enqueue_style(...).", "easy")

    return [w_hook, w_shortcode, w_args, w_theme, w_loop, w_header, w_haveposts, w_enqueue]


def yaml_pool():
    SVC = ["web", "api", "app", "frontend", "worker", "admin", "proxy", "db"]
    PORTS = [3000, 4000, 5000, 8000, 8080, 9000, 5432, 6379, 4000, 9090]
    IMGS = ["node:18", "python:3.11", "nginx:alpine", "redis:7", "postgres:16",
            "ubuntu:24.04", "golang:1.22", "php:8.3"]
    KEYS = ["MODE", "ENV", "LOG_LEVEL", "REGION", "TIMEOUT", "RETRIES", "WORKERS", "DEBUG", "CACHE", "QUEUE"]
    FILES = ["app.py", "index.js", "main.go", "server.php", "worker.js", "api.py", "run.sh", "start.js"]
    PATHS = ["/data", "/app/data", "/var/log", "/srv/static", "/mnt/backup", "/opt/config", "/home/app", "/etc/app"]
    RUNNERS = ["ubuntu-latest", "ubuntu-24.04", "windows-latest", "macos-latest"]
    CMDS = [("node", "index.js"), ("python", "app.py"), ("go", "run main.go"),
            ("php", "server.php"), ("npm", "start"), ("sh", "run.sh")]
    JOBS = ["build", "test", "lint", "deploy", "release", "scan"]

    def y_cmd():
        exe, script = RC(CMDS)
        return bug([f"FROM {RC(IMGS)}", "WORKDIR /app", f"COPY {script} .",
                    f"CMD [\"{exe}\" \"{script}\"]"], 3,
                   "Missing comma inside the CMD JSON array.", "easy")

    def y_ports():
        p = RC(PORTS); s = RC(SVC)
        return bug(["version: '3'", "services:", f"  {s}:", "    build: .", "    ports:",
                    f"      - '{p}-{p}'"], 5,
                   f"Port mapping uses a colon — '{p}-{p}' should be '{p}:{p}' (host:container).", "easy")

    def y_pip():
        return bug(["FROM python:3.11", f"COPY {RC(['requirements.txt', 'req.txt'])} .",
                    "RUN pip install requirements.txt"], 2,
                   "Missing the -r flag — 'pip install -r requirements.txt' installs FROM the file.", "easy")

    def y_on():
        ev = RC(["push", "pull_request", "schedule", "workflow_dispatch"])
        return bug(["name: CI", f"on {ev}:", "jobs:", "  build:", f"    runs-on: {RC(RUNNERS)}"], 1,
                   "YAML key/value split is 'on: <event>', not 'on <event>:' — the colon belongs after 'on'.", "easy")

    def y_dash():
        p = RC(PORTS); s = RC(SVC)
        return bug(["services:", f"  {s}:", f"    image: {RC(IMGS)}", "    ports:", f"      {p}:{p}"], 4,
                   f"List items need a leading dash — '- {p}:{p}'.", "easy")

    def y_colon():
        k = RC(KEYS)
        return bug(["config:", "  server:", f"    {k}: 10:30"], 2,
                   "A value containing ':' must be quoted — '10:30' breaks YAML parsing.", "hard")

    def y_secret():
        sec = RC(["API_KEY", "DB_PASSWORD", "SSH_KEY", "DEPLOY_TOKEN", "AWS_SECRET"])
        return bug(["jobs:", "  deploy:", f"    runs-on: {RC(RUNNERS)}", "    steps:",
                    f"      - run: echo ${{{{ secrets.{sec} }}}}"], 4,
                   f"Echoing secrets.{sec} leaks it in CI logs — secrets must never be printed.", "medium")

    def y_needs():
        j = RC(JOBS)
        return bug(["jobs:", f"  {j.capitalize()}:", f"    runs-on: {RC(RUNNERS)}", "  deploy:",
                    f"    needs: {j}"], 4,
                   f"The job is defined as '{j.capitalize()}' but needs references '{j}' — job ids are case-sensitive.", "hard")

    def y_runson():
        good = RC(RUNNERS)
        bad = good.replace("-", "_") if "-" in good else good + "x"
        return bug(["jobs:", "  build:", f"    runs-on: {bad}"], 2,
                   f"Runner label typo — '{bad}' should be '{good}' (hyphen, exact spelling).", "easy")

    def y_from():
        return bug([f"FORM {RC(IMGS)}", "WORKDIR /app", "COPY . ."], 0,
                   "Dockerfiles start with FROM, not FORM — typo.", "easy")

    def y_copy():
        f = RC(FILES)
        return bug([f"FROM {RC(IMGS)}", f"COPY {f}", f"RUN echo building {f}"], 1,
                   "COPY needs a destination — COPY <src> <dest> (e.g. 'COPY app.py .').", "easy")

    def y_workdir():
        return bug([f"FROM {RC(IMGS)}", f"WORKDIR {RC(['app', 'src', 'home/app', 'opt/app'])}",
                    "COPY . ."], 1,
                   "WORKDIR should be an absolute path starting with '/'.", "medium")

    def y_kind():
        k = RC([("Deployment", "Depoyment"), ("Service", "Servce"), ("ConfigMap", "Configmapm"),
                ("Namespace", "Namespce")])
        return bug(["apiVersion: apps/v1", f"kind: {k[1]}", "metadata:", f"  name: {RC(SVC)}"], 1,
                   f"Kind typo — '{k[1]}' should be '{k[0]}'.", "easy")

    def y_volume():
        hp = RC(PATHS)
        return bug(["docker run -d \\", f"  -v {hp} \\", f"  {RC(IMGS)}"], 1,
                   "Volume mappings need host:container separated by a colon — -v <host>:<container>.", "easy")

    def y_indent():
        s = RC(SVC)
        return bug(["services:", f"{s}:", f"  image: {RC(IMGS)}"], 1,
                   f"'{s}' must be INDENTED under 'services:' — at the same level it's a sibling key, not a service.", "medium")

    def y_env():
        s = RC(SVC); k = RC(KEYS)
        return bug(["services:", f"  {s}:", "    environment:", f"      {k} production"], 3,
                   "Environment entries need 'KEY: value' — the colon is missing.", "easy")

    def y_expose():
        s = RC(SVC); p = RC(PORTS)
        return bug(["services:", f"  {s}:", f"    image: {RC(IMGS)}", f"    expose: '{p}'"], 3,
                   "expose takes a NUMBER, not a quoted string — '3000' ≠ 3000 for port configs.", "medium")

    return [y_cmd, y_ports, y_pip, y_on, y_dash, y_colon, y_secret, y_needs, y_runson,
            y_from, y_copy, y_workdir, y_kind, y_volume, y_indent, y_env, y_expose]


def security_pool():
    URLS = ["/user/:id", "/account/:id", "/profile/:id", "/order/:id", "/invoice/:id",
            "/api/user/:id", "/api/account/:id", "/admin/user/:id"]
    VARS = ["password", "passwd", "secret", "token", "apiKey", "secretKey", "dbPass"]
    USERS = ["ram", "sita", "hari", "gita", "admin", "test"]

    def s_sqli():
        u = RC(URLS)
        if RC(["js", "php"]) == "js":
            return bug([f"app.get('{u}', (req, res) => {{",
                        "  db.query(`SELECT * FROM users WHERE id = ${req.params.id}`);",
                        "  res.send('ok');", "});"], 1,
                       "Template-literal SQL from raw input — SQL injection; use parameterized queries.", "hard")
        return bug(["$id = $_GET['id'];", "$q = \"SELECT * FROM users WHERE id = $id\";",
                    "mysqli_query($conn, $q);"], 1,
                   "GET input interpolated into SQL — SQL injection; use prepared statements.", "hard")

    def s_plain():
        return bug([f"user = User(username='{RC(USERS)}', password='password123')", "user.save()"], 0,
                   "Password stored in plaintext — hash it first (bcrypt/argon2/set_password).", "medium")

    def s_md5():
        algo = RC(["md5", "sha1"])
        return bug(["import hashlib", f"hashed = hashlib.{algo}(password.encode()).hexdigest()"], 1,
                   f"{algo.upper()} is fast and broken for password hashing — use bcrypt/argon2/PBKDF2.", "medium")

    def s_secret():
        v = RC(VARS)
        return bug(["const jwt = require('jsonwebtoken');",
                    f"const token = jwt.sign({{ id }}, '{v}123');"], 1,
                   "Hardcoded weak secret in source — load strong random secrets from environment variables.", "medium")

    def s_idor():
        return bug([f"app.get('{RC(URLS)}', (req, res) => {{", "  const user = db.getUser(req.params.id);",
                    "  res.json(user);", "});"], 0,
                   "No authentication/authorization check before returning user data — IDOR vulnerability.", "hard")

    def s_xss():
        p = RC(["comment", "name", "bio", "message"])
        if RC(["php", "js"]) == "php":
            return bug([f"<input name='{p}'>", f"<?php echo $_POST['{p}']; ?>"], 1,
                       "Echoing raw user input into HTML — XSS; escape with htmlspecialchars().", "medium")
        return bug(["const div = document.getElementById('out');",
                    f"div.innerHTML = userInput;"], 1,
                   "Assigning raw input to innerHTML — XSS; use textContent or sanitize.", "medium")

    def s_eval():
        return bug(["function calc(input) {", "  return eval(input);", "}"], 1,
                   "eval() on user input executes arbitrary code — never eval untrusted data.", "hard")

    def s_token():
        return bug(["const url = 'https://api.example.com/data?token=' + jwt;", "fetch(url);"], 0,
                   "Tokens in URLs leak via logs/history/referrer — send them in the Authorization header.", "hard")

    def s_rand():
        return bug(["function makeToken() {", "  return Math.random().toString(36).slice(2);", "}"], 1,
                   "Math.random is not cryptographically secure — use crypto for tokens.", "medium")

    def s_http():
        return bug(["<form action='http://example.com/login' method='post'>",
                    "  <input name='pass' type='password'>", "</form>"], 0,
                   "Login form posts over plain http:// — credentials travel unencrypted; use https.", "easy")

    def s_logpass():
        return bug(["def login(username, password):", "    print('Login attempt:', username, password)",
                    "    return check(username, password)"], 1,
                   "Logging the raw password to console/logs — sensitive data must never be logged.", "medium")

    def s_dbcreds():
        return bug(["conn = connect(", "    host='db.example.com',",
                    "    user='admin', password='Sup3rS3cret!'", ")"], 2,
                   "Database credentials hardcoded in source — move to environment variables/secret manager.", "medium")

    def s_redirect():
        return bug(["app.get('/go', (req, res) => {", "  res.redirect(req.query.next);", "});"], 1,
                   "Open redirect — redirecting to unvalidated user input can send users to phishing sites.", "hard")

    def s_csrf():
        return bug(["<form action='/transfer' method='post'>",
                    "  <input name='amount'>", "  <input name='to'>", "</form>"], 0,
                   "State-changing form has no CSRF token — attackers can forge requests from other sites.", "hard")

    def s_traversal():
        return bug(["def read_file(name):", "    with open('/data/' + name) as f:", "        return f.read()"], 1,
                   "Path traversal — '../../etc/passwd' as name escapes the folder; validate/basename the path.", "hard")

    def s_cmdinject():
        return bug(["import os", "def ping(host):", "    os.system('ping -c 1 ' + host)"], 2,
                   "Command injection — user input appended to a shell command; use subprocess with a list.", "hard")

    def s_debug():
        return bug(["DEBUG = True", "ALLOWED_HOSTS = ['*']"], 0,
                   "DEBUG=True with wildcard hosts in production — leaks stack traces and widens attack surface.", "medium")

    def s_chmod():
        return bug(["# make files accessible", "chmod -R 777 /var/www/app"], 1,
                   "chmod 777 makes everything world-writable — use least privilege (750/640).", "medium")

    return [s_sqli, s_plain, s_md5, s_secret, s_idor, s_xss, s_eval, s_token, s_rand,
            s_http, s_logpass, s_dbcreds, s_redirect, s_csrf, s_traversal, s_cmdinject,
            s_debug, s_chmod]


def qa_pool():
    EPS = ["signup", "login", "create_order", "update_profile", "search", "upload",
           "reset_password", "checkout", "add_item", "delete_note"]
    CODES = [200, 201, 204, 400, 401, 403, 404, 422, 500]

    def q_eq():
        v = RC(CODES)
        return bug(["def test_create():", f"    result = create({v})", f"    assert result = {v}"], 2,
                   "= assigns inside assert — must be ==.", "easy")

    def q_status():
        bad = RC([200, 201])
        return bug(["def test_login():", "    r = login('user', 'wrongpass')",
                    f"    assert r.status_code == {bad}"], 2,
                   f"A failed login must NOT expect {bad} — it should assert 401/403.", "medium")

    def q_expected():
        return bug(["Test Case: checkout button", "Step 1: Add item to cart", "Step 2: Click checkout",
                    "Expected Result: (not specified)"], 3,
                   "A test case without an expected result cannot be verified.", "hard")

    def q_happy():
        return bug(["Plan: test only the happy path with valid data", "Skip boundary and invalid inputs",
                    "Mark fully tested when happy path passes"], 2,
                   "'Fully tested' after happy-path only is misleading — boundaries and negatives are required.", "hard")

    def q_sleep():
        return bug(["def test_sync():", "    start_sync()", f"    time.sleep({RC([10, 30, 60])})",
                    "    assert done"], 2,
                   "Fixed sleeps make tests slow and flaky — poll for the condition instead.", "medium")

    def q_prod():
        return bug(["# smoke test plan", "1. Run load test against the production database"], 1,
                   "Load-testing production can take the real service down — use staging.", "hard")

    def q_teardown():
        return bug(["def test_upload():", "    create_test_files('/tmp/f')", "    assert upload('/tmp/f')"], 0,
                   "No teardown/cleanup — test files accumulate and poison later runs.", "medium")

    def q_dup():
        e = RC(EPS)
        return bug([f"def test_{e}():", "    assert api_ok()", f"def test_{e}():",
                    "    assert api_fast()"], 2,
                   "Duplicate test names — the second definition shadows the first, so one test silently never runs.", "hard")

    def q_dep():
        return bug(["def test_b_after_a():", "    run_a_first()", "    assert state_ready()"], 0,
                   "Test depends on another test's side effects — tests must be independent or use fixtures.", "medium")

    def q_loc():
        return bug(["def test_get_item():", "    assert get(0) is not None",
                    "    assert get(999999) is None"], 1,
                   "Asserts run before any arrange/setup step — the first assert can crash for empty data.", "easy")

    return [q_eq, q_status, q_expected, q_happy, q_sleep, q_prod, q_teardown, q_dup, q_dep, q_loc]


def genai_pool():
    TOPICS = ["space", "history", "technology", "sports", "music", "science"]
    MODELS = ["gpt-4", "gpt-4o", "gpt-4o-mini"]

    def g_comma():
        return bug(["import openai", "response = openai.ChatCompletion.create(",
                    f"  model='{RC(MODELS)}'", "  messages=[{'role': 'user', 'content': 'Hi'}]", ")"], 2,
                   "Missing comma after the model argument — SyntaxError.", "easy")

    def g_fstring():
        t = RC(TOPICS)
        return bug([f"def build_prompt({t}):", f"    return f'Write about {{{t}s}}'"], 1,
                   "f-string references a different name than the parameter — NameError.", "medium")

    def g_typo():
        return bug(["prompt = \"Summarize: \" + text", "response = model.generate(propmt)"], 1,
                   "'propmt' is a typo of 'prompt' — NameError.", "easy")

    def g_loop():
        return bug(["for doc in documents:", "    embedding = model.encode(doc)",
                    "    embeddings.append(embedding)", "matrix = np.array(embedding)"], 3,
                   "Uses the last loop variable instead of the accumulated 'embeddings' list.", "hard")

    def g_norm():
        return bug(["import numpy as np", "def cosine(a, b):",
                    "    return np.dot(a, b) / (np.norm(a) * np.norm(b))"], 2,
                   "np.norm doesn't exist — it's np.linalg.norm.", "medium")

    def g_global():
        return bug(["chat_history = []", "def chat(msg):", "    chat_history = chat_history + [msg]",
                    "    return model.generate(chat_history)"], 2,
                   "Reassigning before reading raises UnboundLocalError — declare global or use append().", "hard")

    def g_model():
        return bug(["response = client.chat.completions.create(",
                    f"  model='{RC(MODELS).replace('-', '')}',", "  messages=msgs", ")"], 1,
                   "Model id typo — valid ids keep the hyphen (e.g. 'gpt-4', 'gpt-4o').", "easy")

    def g_temp():
        return bug(["response = client.chat.completions.create(", f"  model='{RC(MODELS)}',",
                    "  temperature='medium',", "  messages=msgs", ")"], 2,
                   "temperature is a NUMBER (0–2), not a string.", "easy")

    def g_key():
        return bug(["client = OpenAI(api_key='sk-proj-abc123def456')"], 0,
                   "API key hardcoded in source — load from an environment variable and rotate the leaked key.", "hard")

    def g_json():
        return bug(["import json", "cfg = json.load('{\"debug\": true}')"], 1,
                   "A JSON *string* needs json.loads(); json.load() is for file objects.", "medium")

    return [g_comma, g_fstring, g_typo, g_loop, g_norm, g_global, g_model, g_temp, g_key, g_json]


def pandas_pool():
    COLS = ["age", "salary", "price", "qty", "rating", "marks", "total", "hours"]
    FILES = ["data.csv", "sales.csv", "users.csv", "orders.csv", "logs.csv", "survey.csv"]
    GRP = ["region", "department", "category", "city", "team"]

    def pd_shape():
        return bug(["import pandas as pd", "df = pd.DataFrame(data)", "print(df.shape())"], 2,
                   "df.shape is a property, not a method — drop the ().", "easy")

    def pd_eq():
        return bug(["import pandas as pd", f"df = pd.read_csv('{RC(FILES)}')",
                    f"adults = df[df['{RC(COLS)}'] = 25]"], 2,
                   "= assigns inside the filter — use ==.", "medium")

    def pd_paren():
        return bug(["import pandas as pd", f"df = pd.read_csv('{RC(FILES)}')", "print(df.head()"], 2,
                   "Missing closing parenthesis on df.head().", "easy")

    def pd_sort():
        return bug([f"sales = df.groupby('{RC(GRP)}')['{RC(['sales', 'amount', 'total'])}'].sum()",
                    "top = sales.sort_values().head(3)"], 1,
                   "sort_values() defaults to ASCENDING — head() then returns the LOWEST; use ascending=False.", "hard")

    def pd_dropna():
        return bug([f"df = pd.read_csv('{RC(FILES)}')", "df.dropna()", "df.to_csv('clean.csv')"], 1,
                   "dropna() returns a NEW frame — without inplace=True or reassignment nothing is dropped.", "medium")

    def pd_file():
        f = RC(FILES)
        return bug(["import pandas as pd", f"df = pd.read_csv('{f[:-4]}.csx')"], 1,
                   f"File extension typo — '{f[:-4]}.csx' should be '{f}'.", "easy")

    def pd_plt():
        return bug(["import matplotlib.pyplot as plt", "data = [10, 20, 15, 30]",
                    "plt.bar(range(len(data), data)", "plt.show()"], 2,
                   "Parenthesis mismatch — range(len(data) never closes before the comma.", "medium")

    def pd_loc():
        return bug(["df = pd.DataFrame({'a': [1, 2, 3})", "print(df.loc[2])"], 0,
                   "Unbalanced parenthesis in the DataFrame constructor.", "easy")

    def pd_chain():
        return bug([f"df = pd.read_csv('{RC(FILES)}')",
                    "df[df['age'] > 30]['city'] = 'Kathmandu'"], 1,
                   "Chained-indexing assignment — pandas silently ignores it; use df.loc[df['age'] > 30, 'city'] = ....", "hard")

    return [pd_shape, pd_eq, pd_paren, pd_sort, pd_dropna, pd_file, pd_plt, pd_loc, pd_chain]


def sqlbug_pool():
    TABLES = ["employees", "orders", "products", "users", "students", "invoices", "movies", "books"]
    TEXTCOLS = [("city", ["Kathmandu", "Pokhara", "Lalitpur"]),
                ("status", ["active", "pending", "paid"]),
                ("category", ["Electronics", "Books", "Toys"]),
                ("role", ["admin", "user", "guest"])]

    def sb_group():
        t = RC(TABLES)
        return bug([f"SELECT category, COUNT(*) FROM {t}", "GROUP category;"], 1,
                   "Missing BY — it must be GROUP BY category.", "easy")

    def sb_comma():
        c1, c2, t = RC(["name", "price", "title", "email"]), RC(["price", "qty", "total", "rating"]), RC(TABLES)
        return bug([f"SELECT {c1} {c2} FROM {t};"], 0,
                   "Missing comma between columns — 'a b' parses as 'a AS b'.", "easy")

    def sb_null():
        return bug([f"SELECT * FROM {RC(TABLES)}", "WHERE category = NULL;"], 1,
                   "= NULL never matches — NULL comparisons need IS NULL.", "medium")

    def sb_like():
        return bug(["SELECT * FROM users", "WHERE name LIKE 'A';"], 1,
                   "LIKE 'A' matches only exactly 'A' — a starts-with search needs 'A%'.", "easy")

    def sb_delete():
        t = RC(TABLES)
        return bug([f"-- goal: remove only cancelled rows from {t}", f"DELETE FROM {t};"], 1,
                   "DELETE without WHERE wipes the whole table.", "hard")

    def sb_quote():
        col, vals = RC(TEXTCOLS); v = RC(vals)
        return bug([f"SELECT * FROM {RC(TABLES)}", f"WHERE {col} = {v};"], 1,
                   f"String literal needs quotes — '{v}' (otherwise it's parsed as a column name).", "easy")

    def sb_join():
        return bug(["SELECT c.name, o.total", "FROM customers c JOIN orders o;",
                    "WHERE c.id = o.customer_id;"], 1,
                   "JOIN has no ON condition — it becomes a full cross join before the WHERE.", "hard")

    def sb_stray():
        return bug([f"SELECT COUNT(name), FROM {RC(TABLES)};"], 0,
                   "Stray comma before FROM — invalid syntax.", "easy")

    return [sb_group, sb_comma, sb_null, sb_like, sb_delete, sb_quote, sb_join, sb_stray]


def marketing_pool():
    CTX = {"platform": ["Instagram", "Facebook", "TikTok", "LinkedIn", "YouTube", "X"],
           "content": ["video", "reel", "blog post", "carousel", "story", "newsletter"],
           "audience": ["audience", "followers", "customers", "viewers", "subscribers"],
           "channel": ["email", "social", "search", "paid ads", "influencers"]}
    T = []

    def mk(steps, idx, note, diff="medium"):
        def gen():
            c = {k: random.choice(v) for k, v in CTX.items()}
            return bug([s.format(**c) for s in steps], idx, note, diff)
        T.append(gen)

    mk(["Step 1: Define the target {audience} for the {content}",
        "Step 2: Set campaign goals with no measurable KPI on {platform}",
        "Step 3: Launch the {channel} campaign"], 1,
       "Goals without a measurable KPI can never be judged a success or failure.")
    mk(["Step 1: Set the monthly {channel} budget",
        "Step 2: Run the exact same {content} creative for 6 months on {platform}",
        "Step 3: Review {audience} metrics weekly"], 1,
       "Creative fatigue — audiences tune out; refresh creatives regularly.")
    mk(["Step 1: Import the full email list including unsubscribed {audience}",
        "Step 2: Segment by {content} interest",
        "Step 3: Send the {channel} campaign"], 0,
       "Emailing unsubscribed users breaks anti-spam laws (GDPR/CAN-SPAM).")
    mk(["Step 1: Promise 'guaranteed #1 ranking in 24 hours' in the {channel} headline",
        "Step 2: Launch the {content} campaign on {platform}"], 0,
       "Unverifiable guarantees break ad policies and destroy trust.")
    mk(["Step 1: Build a dedicated landing page for the {content}",
        "Step 2: Send all {channel} traffic to the homepage instead",
        "Step 3: Measure conversion of {audience}"], 1,
       "Targeted traffic sent to the generic homepage kills conversion; use the matching landing page.")
    mk(["Step 1: Post the identical {content} at the same time on every {platform}",
        "Step 2: Reuse the same caption for the {audience}"], 0,
       "Each platform's audience/format differs — tailor content per platform.")
    mk(["Step 1: Track engagement rate on {platform}",
        "Step 2: Buy 10k fake {audience}",
        "Step 3: Analyze top {content} formats"], 1,
       "Fake followers inflate vanity metrics, tank engagement rate and risk penalties.")
    mk(["Step 1: Schedule the {content} with a calendar",
        "Step 2: Ignore all negative comments from {audience}",
        "Step 3: Post 3-4x a week on {platform}"], 1,
       "Ignoring negative comments erodes brand trust — respond professionally.")
    mk(["Step 1: Publish the {content} with no captions or subtitles",
        "Step 2: Share it on {platform} for the {audience}"], 0,
       "Most social content is watched muted — without captions the message is lost.")
    mk(["Step 1: Run a {platform} giveaway requiring 20 friend tags to enter",
        "Step 2: Announce the winner to your {audience}"], 0,
       "Tag-to-enter giveaways violate platform rules and attract disengaged followers.")
    mk(["Step 1: Research keywords for the {content}",
        "Step 2: Repeat the keyword 30 times in the {content} for SEO",
        "Step 3: Add a CTA for the {audience}"], 1,
       "Keyword stuffing is penalized and unreadable — write naturally.")
    mk(["Step 1: Draft the {content} for {platform}",
        "Step 2: Publish immediately without proofreading"], 1,
       "Skipping proofreading ships typos that hurt credibility.")
    mk(["Step 1: Study a competitor's hit {content} on {platform}",
        "Step 2: Copy it and change a few words",
        "Step 3: Republish as yours to your {audience}"], 1,
       "Light-edit copying is plagiarism — legal and SEO penalties.")
    mk(["Step 1: Write the {content} with no meta description",
        "Step 2: Publish and share on {platform}"], 0,
       "Missing meta description hurts click-through from search results.")
    mk(["Step 1: Build brand voice guidelines for {platform}",
        "Step 2: Write every {content} in a generic voiceless tone for the {audience}"], 1,
       "No brand voice = forgettable content; consistency builds recognition.")
    mk(["Step 1: Plan 10 {content} posts a day on {platform} to maximize reach",
        "Step 2: Ignore {channel} analytics"], 0,
       "Spam-frequency posting plus ignoring analytics burns out the audience.")
    mk(["Step 1: Buy an email list of 50k {audience} addresses",
        "Step 2: Send the {channel} newsletter"], 0,
       "Purchased lists have no consent — bounces, spam traps and legal risk.")
    mk(["Step 1: Use a clickbait headline the {content} can't deliver",
        "Step 2: Promote it heavily on {channel}"], 0,
       "Promise-mismatch clickbait destroys trust and triggers penalties.")
    mk(["Step 1: Design a beautiful {content} for {platform}",
        "Step 2: Forget any call-to-action for the {audience}"], 1,
       "Without a CTA the audience has no next step — conversions die.")
    mk(["Step 1: Target every {audience} aged 18-65 on {platform}",
        "Step 2: Spend the full {channel} budget at once"], 0,
       "No audience segmentation = wasted spend; start narrow, then scale.")
    mk(["Step 1: Launch the {content} campaign",
        "Step 2: Never check {platform} analytics or {channel} performance"], 1,
       "Launching without measurement means you can't improve or prove ROI.")
    mk(["Step 1: Post the same {content} on {platform} 5 times a day",
        "Step 2: Delete any negative comment from the {audience}"], 1,
       "Spam frequency PLUS deleting criticism both damage the brand.")
    return T


def design_pool():
    CTX = {"medium": ["poster", "brochure", "banner", "flyer", "business card", "packaging"],
           "product": ["app", "website", "dashboard", "landing page", "checkout flow"]}
    T = []

    def mk(steps, idx, note, diff="medium"):
        def gen():
            c = {k: random.choice(v) for k, v in CTX.items()}
            return bug([s.format(**c) for s in steps], idx, note, diff)
        T.append(gen)

    mk(["Step 1: Set canvas to 72 DPI for the print {medium}",
        "Step 2: Ship it as the {product} hero asset"], 0,
       "Print needs at least 300 DPI — 72 DPI is for screens only.", "easy")
    mk(["Step 1: Design the {medium} in RGB for print",
        "Step 2: Convert to CMYK at the very end for the {product} launch"], 0,
       "Design print in CMYK from the start — late conversion shifts colors.", "medium")
    mk(["Step 1: Pick the palette for the {medium}",
        "Step 2: Use 6 different fonts on the {medium}",
        "Step 3: Apply the same chaos to the {product}"], 1,
       "Too many fonts break consistency — stick to 2-3.", "medium")
    mk(["Step 1: Export the {medium} logo only as JPEG",
        "Step 2: Deliver to the {product} team"], 0,
       "Logos need transparent scalable formats (SVG/PNG) — JPEG has a background and degrades.", "easy")
    mk(["Step 1: Use bright neon for all body text on the {medium}",
        "Step 2: Reuse it across the {product} screens"], 0,
       "Neon body text is unreadable at length — use it sparingly as accent.", "easy")
    mk(["Step 1: Interview {product} users",
        "Step 2: Skip wireframes, jump to hi-fi mockups",
        "Step 3: Ship the {medium} assets"], 1,
       "Skipping wireframes locks expensive decisions before flows are validated.", "easy")
    mk(["Step 1: Design 44x44px tap targets for the {product}",
        "Step 2: Use icon-only navigation with no labels"], 1,
       "Icon-only nav hurts discoverability — add labels.", "medium")
    mk(["Step 1: Map the {product} persona",
        "Step 2: Build a 12-step onboarding",
        "Step 3: Promote with the {medium}"], 1,
       "12 steps is massive drop-off — shorten onboarding.", "hard")
    mk(["Step 1: Sketch 5 {medium} concepts",
        "Step 2: Pick idea #1 without comparing",
        "Step 3: Apply it to the {product} directly"], 1,
       "Committing without comparison skips exploration that finds better solutions.", "easy")
    mk(["Step 1: Design {product} error states",
        "Step 2: Show one generic 'Something went wrong' for every failure"], 1,
       "Generic errors don't tell users how to fix the problem.", "hard")
    mk(["Step 1: Style the {product} card",
        "Step 2: Use #cccccc text on white"], 1,
       "Light gray on white fails WCAG contrast.", "easy")
    mk(["Step 1: Build the {product} mobile nav",
        "Step 2: Give links 2px padding"], 1,
       "Tap targets under ~44x44px are hard to hit.", "medium")
    mk(["Step 1: Use placeholder text as the only label in the {product} form"], 0,
       "Placeholders vanish while typing — keep a real label.", "medium")
    mk(["Step 1: Add an icon button with no alt/aria-label in the {medium}"], 0,
       "No accessible name — screen reader users can't tell what it does.", "easy")
    mk(["Step 1: Make account deletion a single tap in the {product}"], 0,
       "Destructive action needs a confirmation step.", "easy")
    mk(["Step 1: Show a spinner on {product} submit",
        "Step 2: Never dismiss it on failure"], 1,
       "A spinner that never clears traps users — surface errors.", "medium")
    mk(["Step 1: Typeset the {medium}",
        "Step 2: Set body copy at 10px for style"], 1,
       "10px body text fails readability — keep >= ~14px equivalent.", "easy")
    mk(["Step 1: Lay out the {medium} freely",
        "Step 2: Use no grid or spacing system for the {product}"], 1,
       "No grid = inconsistent alignment and spacing.", "medium")
    mk(["Step 1: Design the {medium} in one visual style",
        "Step 2: Build the {product} screens in a totally different style"], 1,
       "Inconsistent visual language between assets confuses users and weakens the brand.", "medium")
    mk(["Step 1: Skip research, start the {product} mockups immediately",
        "Step 2: Ship the {medium} assets the same day"], 0,
       "No research or discovery = designing for assumptions, not users.", "medium")
    mk(["Step 1: Fill the {medium} edge-to-edge with text",
        "Step 2: Leave no margins or safe area for the {product}"], 0,
       "No margins/whitespace = cramped, unreadable layouts (and print gets cut off at the trim edge).", "easy")
    mk(["Step 1: Pick colors for the {medium} by personal taste only",
        "Step 2: Ignore the {product} brand palette"], 1,
       "Ignoring the established brand palette fragments brand identity.", "medium")
    return T


# ============================================================
# 5) Field → shared-pool mapping (each field composes to 500+)
# ============================================================

FIELD_POOLS = {
    "fullstack": ["js", "htmlcss", "sqlbug"],
    "mern": ["js", "node", "react"],
    "react": ["react", "js", "htmlcss"],
    "nextjs": ["next", "react", "js", "node"],
    "laravel": ["php", "laravel", "sqlbug", "js"],
    "django": ["python", "django", "sqlbug"],
    "wordpress": ["php", "wp", "htmlcss", "js"],
    "flutter": ["dart"],
    "crossplatform": ["react", "js", "node"],
    "uiux": ["design", "htmlcss"],
    "graphics": ["design", "htmlcss"],
    "productdesign": ["design", "htmlcss"],
    "python": ["python"],
    "data": ["pandas", "python", "sqlbug"],
    "iot": ["c"],
    "smartiot": ["c", "yaml"],
    "cybersecurity": ["security", "php", "js"],
    "qa": ["qa", "python"],
    "devops": ["yaml"],
    "digitalmarketing": ["marketing"],
    "socialmedia": ["marketing"],
    "contentmarketing": ["marketing"],
    "projectbased": ["js", "python"],
    "internship": ["js", "python"],
    "genai": ["genai", "python"],
    "cpp": ["c"],
}


# ============================================================
# 6) Build & write questions.json
# ============================================================

def validate_mcq(q):
    assert isinstance(q["objective"], str) and q["objective"]
    assert len(q["options"]) == 4 and len(set(q["options"])) == 4, f"bad options: {q['objective']}"
    assert 0 <= q["correctIndex"] < 4


def validate_bug(c):
    assert isinstance(c["lines"], list) and len(c["lines"]) >= 1
    assert 0 <= c["bugIndex"] < len(c["lines"])
    assert c["difficulty"] in ("easy", "medium", "hard")


def main():
    print("Generating SATRI Arcade question bank…\n")

    print("MCQ sections:")
    sql = build_mcq_pool([sql_where_num, sql_where_text, sql_order, sql_topn, sql_count_agg,
                          sql_group_having, sql_distinct_like, sql_between_in_null, sql_dml,
                          sql_joins, sql_misc], 500, "SQL")
    git = build_mcq_pool([git_branch_tasks, git_remote_tasks, git_stage_file_tasks,
                          git_history_tasks, git_undo_tasks, git_misc_tasks,
                          git_more_tasks], 500, "Git")

    print("\nBug Hunter shared pools:")
    pool_targets = {
        "python": (python_pool(), 540),
        "pandas": (pandas_pool(), 80),
        "js": (js_pool(), 305),
        "htmlcss": (htmlcss_pool(), 170),
        "node": (node_pool(), 100),
        "react": (react_pool(), 110),
        "next": (next_pool(), 25),
        "php": (php_pool(), 155),
        "laravel": (laravel_pool(), 40),
        "django": (django_pool(), 22),
        "wp": (wp_pool(), 20),
        "dart": (dart_pool(), 500),
        "c": (c_pool(), 520),
        "yaml": (yaml_pool(), 500),
        "security": (security_pool(), 48),
        "marketing": (marketing_pool(), 500),
        "design": (design_pool(), 330),
        "qa": (qa_pool(), 30),
        "genai": (genai_pool(), 20),
        "sqlbug": (sqlbug_pool(), 100),
    }
    shared = {}
    for name, (pats, target) in pool_targets.items():
        shared[name] = build_bug_pool(pats, target, name)

    # validate everything
    for q in sql + git:
        validate_mcq(q)
    for pool in shared.values():
        for c in pool:
            validate_bug(c)
    for w in WORDS:
        assert w.isalpha() and w.islower()

    # verify every field composes to 500+
    print("\nField composition check (must be 500+ each):")
    problems = []
    for field, keys in FIELD_POOLS.items():
        n = sum(len(shared[k]) for k in keys)
        status = "OK" if n >= 500 else "SHORT"
        if n < 500:
            problems.append(field)
        print(f"  {field:18s} = {'+'.join(str(len(shared[k])) for k in keys)} = {n}  [{status}]")
    assert not problems, f"fields under 500: {problems}"

    bank = {
        "meta": {
            "name": "SATRI Arcade Question Bank",
            "generated": str(date.today()),
            "generator": "generate_bank.py (template-based generation, seed 20260822)",
            "counts": {
                "sql": len(sql),
                "git": len(git),
                "words": len(WORDS),
                "bugSharedPools": {k: len(v) for k, v in shared.items()},
                "bugUniqueChallenges": sum(len(v) for v in shared.values()),
                "fields": {f: sum(len(shared[k]) for k in keys) for f, keys in FIELD_POOLS.items()},
            },
            "sources": "Template-generated originals for this project + v1 curated set. See README.md.",
        },
        "sql": sql,
        "git": git,
        "words": WORDS,
        "bugShared": shared,
        "bugFieldPools": FIELD_POOLS,
        "bug": {},
    }

    out = "questions.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, separators=(",", ":"))

    import os
    print(f"\n✔ Wrote {out} ({os.path.getsize(out) / 1024:.0f} KB)")
    print(f"  SQL {len(sql)} · Git {len(git)} · Words {len(WORDS)}")
    print(f"  Bug Hunter: {sum(len(v) for v in shared.values())} unique challenges across "
          f"{len(shared)} shared pools, {len(FIELD_POOLS)} fields x 500+")


if __name__ == "__main__":
    main()
