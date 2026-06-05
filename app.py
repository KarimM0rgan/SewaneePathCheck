# CS284 Final Project
# Karim Morgan & Safae Berhenich

import re
from flask import Flask, render_template, request, redirect, url_for
from db import get_db

app = Flask(__name__)

def requirement_table(kind):
    return ("major_requirements", "major_id") if kind == "major" else ("minor_requirements", "minor_id")

def all_programs(cursor):
    cursor.execute("""
        select major_id as id, major_name as name, 'major' as kind,
               (select count(*) from major_requirements mr where mr.major_id = majors.major_id) as req_count
        from majors
        union
        select minor_id, minor_name, 'minor',
               (select count(*) from minor_requirements nr where nr.minor_id = minors.minor_id)
        from minors
        order by name
    """)
    return cursor.fetchall()

def program_by_id(cursor, prog_id, kind):
    if kind == "major":
        cursor.execute("select major_id, major_name from majors where major_id = %s", (prog_id,))
    else:
        cursor.execute("select minor_id, minor_name from minors where minor_id = %s", (prog_id,))
    return cursor.fetchone()

def overlap_verdict(count):
    if count <= 2:
        return "ok", f"{count} overlapping course(s) — within the two-course limit."
    return "exceeds", f"{count} overlapping course(s) — over the two-course limit."

@app.route("/")
def index():
    db = get_db()
    cur = db.cursor()
    programs = all_programs(cur)
    db.close()
    return render_template("index.html", programs=programs, active_page="student")

@app.route("/results", methods=["POST"])
def results():
    prog1_raw = request.form.get("program1", "")
    prog2_raw = request.form.get("program2", "")

    pattern = re.compile(r"^(major|minor)-(\d+)$")
    m1 = pattern.match(prog1_raw)
    m2 = pattern.match(prog2_raw)

    if not m1 or not m2:
        return render_template("results.html", error="Please select two programs with loaded requirements.", active_page="student")

    kind1, id1 = m1.group(1), int(m1.group(2))
    kind2, id2 = m2.group(1), int(m2.group(2))

    if prog1_raw == prog2_raw:
        return render_template("results.html", error="Please select two different programs.", active_page="student")

    db = get_db()
    cur = db.cursor()

    p1 = program_by_id(cur, id1, kind1)
    p2 = program_by_id(cur, id2, kind2)

    tbl1, idcol1 = requirement_table(kind1)
    tbl2, idcol2 = requirement_table(kind2)

    # Check whether selected programs have data.
    # unloaded programs are disabled in the dropdown.
    cur.execute(f"select count(*) from {tbl1} where {idcol1} = %s", (id1,))
    req1 = cur.fetchone()[0]
    cur.execute(f"select count(*) from {tbl2} where {idcol2} = %s", (id2,))
    req2 = cur.fetchone()[0]
    if req1 == 0 or req2 == 0:
        db.close()
        return render_template(
            "results.html",
            error="Data failed to load for one of the selected programs. Please double-check the official requirements page.",
            active_page="student"
        )

    cur.execute(f"""
        select c.course_code, c.course_title,
               r1.requirement_type as type_in_first,
               r2.requirement_type as type_in_second
        from   {tbl1} r1
        join   {tbl2} r2 on r1.course_id = r2.course_id
        join   courses c on c.course_id = r1.course_id
        where  r1.{idcol1} = %s
        and    r2.{idcol2} = %s
        order  by
          case when r1.requirement_type = 'core' and r2.requirement_type = 'core' then 0 else 1 end,
          c.course_code
    """, (id1, id2))
    all_direct_overlaps = cur.fetchall()

    core_overlaps = [r for r in all_direct_overlaps if r[2] == "core" and r[3] == "core"]
    elective_or_alternative_overlaps = [r for r in all_direct_overlaps if not (r[2] == "core" and r[3] == "core")]

    # overlaps based on equivalencies
    cur.execute(f"""
        select c1.course_code, c1.course_title,
               c2.course_code, c2.course_title,
               eq.explanation
        from   {tbl1} r1
        join   {tbl2} r2 on r2.{idcol2} = %s
        join   equivalencies eq
               on (eq.course_a_id = r1.course_id and eq.course_b_id = r2.course_id)
               or (eq.course_b_id = r1.course_id and eq.course_a_id = r2.course_id)
        join   courses c1 on c1.course_id = r1.course_id
        join   courses c2 on c2.course_id = r2.course_id
        where  r1.{idcol1} = %s
        and    r1.course_id != r2.course_id
        order  by c1.course_code, c2.course_code
    """, (id2, id1))
    equiv_overlaps = cur.fetchall()

    # For major-major, it asks for core-core overlaps plus equivalencies.
    # For major-minor/minor-minor, we count all shared requirements because electives can still create overlap conflicts depending on the student's choices
    if kind1 == "major" and kind2 == "major":
        overlap_count = len(core_overlaps) + len(equiv_overlaps)
        count_note = "Major-major verdict counts core-core overlaps plus same-requirement equivalencies."
    else:
        overlap_count = len(all_direct_overlaps) + len(equiv_overlaps)
        count_note = "Major/minor verdict counts shared required, elective, and alternative requirement rows because those can become overlap conflicts."

    verdict_key, verdict = overlap_verdict(overlap_count)
    db.close()

    return render_template(
        "results.html",
        p1=p1,
        p2=p2,
        core_overlaps=core_overlaps,
        elective_or_alternative_overlaps=elective_or_alternative_overlaps,
        equiv_overlaps=equiv_overlaps,
        overlap_count=overlap_count,
        verdict_key=verdict_key,
        verdict=verdict,
        count_note=count_note,
        active_page="student",
    )

@app.route("/advisor")
def advisor():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        select a.program_name as program_1,
               b.program_name as program_2,
               count(distinct a.course_id) as shared_core_courses
        from
            (
              select concat('major-', m.major_id) as program_key,
                     m.major_name as program_name,
                     mr.course_id
              from majors m
              join major_requirements mr on mr.major_id = m.major_id
              where mr.requirement_type = 'core'
              union all
              select concat('minor-', n.minor_id),
                     n.minor_name,
                     nr.course_id
              from minors n
              join minor_requirements nr on nr.minor_id = n.minor_id
              where nr.requirement_type = 'core'
            ) a
        join
            (
              select concat('major-', m.major_id) as program_key,
                     m.major_name as program_name,
                     mr.course_id
              from majors m
              join major_requirements mr on mr.major_id = m.major_id
              where mr.requirement_type = 'core'
              union all
              select concat('minor-', n.minor_id),
                     n.minor_name,
                     nr.course_id
              from minors n
              join minor_requirements nr on nr.minor_id = n.minor_id
              where nr.requirement_type = 'core'
            ) b
            on a.course_id = b.course_id
           and a.program_key < b.program_key
        group by a.program_key, b.program_key, a.program_name, b.program_name
        having count(distinct a.course_id) > 2
        order by shared_core_courses desc, program_1, program_2
    """)
    conflict_pairs = cur.fetchall()

    cur.execute("select count(*) from majors")
    major_count = cur.fetchone()[0]
    cur.execute("select count(*) from minors")
    minor_count = cur.fetchone()[0]
    total_programs = major_count + minor_count
    total_pairs = total_programs * (total_programs - 1) // 2
    db.close()

    return render_template(
        "advisor.html",
        conflict_pairs=conflict_pairs,
        conflict_count=len(conflict_pairs),
        total_pairs=total_pairs,
        total_programs=total_programs,
        active_page="advisor",
    )

@app.route("/department-chair")
def department_chair():
    dept_id = request.args.get("dept", type=int)

    db = get_db()
    cur = db.cursor()
    cur.execute("select department_id, department_name from departments order by department_name")
    departments = cur.fetchall()

    selected_dept = None
    hot_courses = []

    if dept_id:
        cur.execute("select department_name from departments where department_id = %s", (dept_id,))
        row = cur.fetchone()
        selected_dept = row[0] if row else None

        cur.execute("""
            select c.course_code,
                   c.course_title,
                   count(distinct x.program_key) as program_count,
                   group_concat(distinct x.program_name order by x.program_name separator ', ') as programs
            from courses c
            join
                (
                  select concat('major-', m.major_id) as program_key,
                         m.major_name as program_name,
                         mr.course_id
                  from majors m
                  join major_requirements mr on mr.major_id = m.major_id
                  where mr.requirement_type = 'core'
                  union all
                  select concat('minor-', n.minor_id),
                         n.minor_name,
                         nr.course_id
                  from minors n
                  join minor_requirements nr on nr.minor_id = n.minor_id
                  where nr.requirement_type = 'core'
                ) x
                on x.course_id = c.course_id
            where c.department_id = %s
            group by c.course_id, c.course_code, c.course_title
            having count(distinct x.program_key) >= 3
            order by program_count desc, c.course_code
        """, (dept_id,))
        hot_courses = cur.fetchall()

    db.close()
    return render_template(
        "department_chair.html",
        departments=departments,
        dept_id=dept_id,
        selected_dept=selected_dept,
        hot_courses=hot_courses,
        active_page="chair",
    )

@app.route("/programs")
def programs():
    search = request.args.get("q", "").strip()
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        select major_id as id, major_name as name, 'major' as kind,
               (select count(*) from major_requirements mr where mr.major_id = majors.major_id) as req_count
        from majors
        union
        select minor_id, minor_name, 'minor',
               (select count(*) from minor_requirements nr where nr.minor_id = minors.minor_id)
        from minors
        order by name
    """)
    rows = cur.fetchall()
    db.close()

    filtered = rows
    regex_error = None
    if search:
        try:
            pat = re.compile(search, re.IGNORECASE)
            filtered = [r for r in rows if pat.search(r[1])]
        except re.error:
            regex_error = f'"{search}" is not a valid regular expression.'
            filtered = rows

    return render_template("programs.html", programs=filtered, search=search, regex_error=regex_error, active_page="student")

@app.route("/conflicts")
def conflicts():
    return redirect(url_for("advisor"))

@app.route("/hot-courses")
def hot_courses():
    return redirect(url_for("department_chair"))

if __name__ == "__main__":
    app.run(debug=True, port=5010)
