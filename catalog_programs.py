# CS284 Final Project
# Safae Berhenich $ Karim Morgan

# URL-List web crawler that uses URLs stored in program_urls_used.txt

import html
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from db import get_db


COURSE_RE = re.compile(r"\b([A-Z]{2,5})\s+(\d{3}[A-Z]?)\b")
URL_FILE = Path(__file__).with_name("program_urls_used.txt")
SLEEP_SECONDS = 0.15

VALIDATION_MIN_ROWS = {
    "Economics Major": 7,
    "Economics Minor": 4,
    "Computer Science Major": 7,
    "Computer Science Minor": 2,
    "Data Science Major": 7,
    "Data Science Minor": 4,
    "Mathematics Major": 6,
    "Mathematics Minor": 3,
    "Biology Major": 2,
    "Biology Minor": 2,
    "Psychology Major": 4,
    "Psychology Minor": 3,
    "Politics Major": 4,
    "Politics Minor": 3,
    "English Major": 3,
    "Chemistry Major": 4,
}


class VisibleTextParser(HTMLParser):
    """Collect visible text while skipping script/style/nav/footer."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_stack = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer"}:
            self.skip_stack.append(tag)

    def handle_endtag(self, tag):
        if self.skip_stack and tag == self.skip_stack[-1]:
            self.skip_stack.pop()

    def handle_data(self, data):
        if not self.skip_stack and data.strip():
            self.parts.append(html.unescape(data.strip()))

    def text(self):
        return " ".join(self.parts)


def parse_program_url_line(line):
    """
    Example:
    Economics major — https://...
    Returns: ("Economics Major", "major", "https://...")
    """
    if "—" not in line:
        return None

    label, url = [part.strip() for part in line.split("—", 1)]
    lower = label.lower()

    if lower.endswith(" major"):
        base = label[:-6].strip()
        kind = "major"
        name = f"{base} Major"
    elif lower.endswith(" minor"):
        base = label[:-6].strip()
        kind = "minor"
        name = f"{base} Minor"
    else:
        return None

    return name, kind, url


def load_program_url_list():
    if not URL_FILE.exists():
        raise FileNotFoundError(
            "program_urls_used.txt is missing. Put it in the same folder as catalog_programs.py."
        )

    programs = []
    seen = set()

    for raw_line in URL_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        parsed = parse_program_url_line(line)
        if not parsed:
            continue

        name, kind, url = parsed
        key = (name.lower(), kind)
        if key not in seen:
            seen.add(key)
            programs.append((name, kind, url))

    return programs


def fetch(url):
    base_url, _fragment = urldefrag(url)
    req = Request(base_url, headers={"User-Agent": "Sewanee PathCheck CS284 student project"})
    with urlopen(req, timeout=35) as response:
        return response.read().decode("utf-8", errors="replace")


def slice_html_to_fragment(raw_html, url):
    """
    If the URL contains #majorstext or #minorstext, start near that HTML anchor.
    This avoids using a fragile hard-coded list of quote strings.
    """
    base_url, fragment = urldefrag(url)
    if not fragment:
        return raw_html

    pattern = re.compile(
        r"(?:id|name)\s*=\s*['\"]" + re.escape(fragment) + r"['\"]",
        re.IGNORECASE,
    )

    match = pattern.search(raw_html)
    if not match:
        return raw_html

    start = max(0, match.start() - 300)
    segment = raw_html[start:]

    stop_pattern = re.compile(
        r"(?:id|name)\s*=\s*['\"](?:majorstext|minorstext|minortext|majortext|certificatetext|certificatestext)['\"]",
        re.IGNORECASE,
    )

    stops = []
    for stop in stop_pattern.finditer(segment):
        if stop.start() > 500:
            stops.append(stop.start())

    if stops:
        segment = segment[: min(stops)]

    return segment


def visible_text_from_html(raw_html):
    parser = VisibleTextParser()
    parser.feed(raw_html)
    return " ".join(parser.text().replace("\xa0", " ").split())


def requirement_text_for_page(url, kind):
    raw = fetch(url)
    sliced = slice_html_to_fragment(raw, url)
    text = visible_text_from_html(sliced)

    lower = text.lower()

    if kind == "major":
        starts = [
            "requirements for the major",
            "requirements for a major",
            "major requirements",
            "requirements for the major in",
        ]
        stops = [
            "requirements for the minor",
            "minor requirements",
            "honors",
            "student learning outcomes",
            "courses",
            "print options",
        ]
    else:
        starts = [
            "requirements for the minor",
            "requirements for a minor",
            "minor requirements",
            "requirements for the minor in",
        ]
        stops = [
            "requirements for the major",
            "major requirements",
            "honors",
            "student learning outcomes",
            "courses",
            "print options",
        ]

    start_idx = -1
    for phrase in starts:
        idx = lower.find(phrase)
        if idx != -1:
            start_idx = idx
            break

    if start_idx != -1:
        cut = text[start_idx:]
        lower_cut = cut.lower()
        end_idx = len(cut)

        total_match = re.search(r"total semester hours\s+\d+", lower_cut)
        if total_match and total_match.end() > 100:
            end_idx = total_match.end() + 60
        else:
            for stop in stops:
                idx = lower_cut.find(stop, 250)
                if idx != -1 and idx < end_idx:
                    end_idx = idx

        text = cut[:end_idx]

    return text


def guess_title(text, end_index):
    after = re.sub(r"\s+", " ", text[end_index:end_index + 180]).strip(" .:-–—")

    next_course = COURSE_RE.search(after)
    if next_course:
        after = after[:next_course.start()].strip(" .:-–—")

    title = re.split(
        r"\s+(Credit|Credits|Hour|Hours|Semester|Prerequisite|Corequisite|Description|Select|Total)\b",
        after,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" .:-–—")

    title = re.sub(r"\s+[1-5]$", "", title).strip()

    if not title or len(title) < 3 or len(title) > 80:
        return "See catalog page"

    return title


def guess_requirement_type(text, start, end):
    context = text[max(0, start - 190):min(len(text), end + 190)].lower()
    before = text[max(0, start - 60):start].lower()

    if re.search(r"\bor\b", before[-30:]) or " or " in context[:130]:
        return "alternative"
    if "select" in context or "choose" in context or "elective" in context:
        return "elective"
    return "core"


def scrape_program_courses(name, kind, url):
    text = requirement_text_for_page(url, kind)

    rows = []
    seen = set()

    for match in COURSE_RE.finditer(text):
        code = f"{match.group(1)} {match.group(2)}"
        if code in seen:
            continue

        seen.add(code)
        title = guess_title(text, match.end())
        requirement_type = guess_requirement_type(text, match.start(), match.end())
        rows.append((code, title, requirement_type))

    return rows


def get_or_create_department(cur, name):
    cur.execute("select department_id from departments where department_name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute("select coalesce(max(department_id), 0) + 1 from departments")
    dept_id = cur.fetchone()[0]
    cur.execute("insert into departments (department_id, department_name) values (%s, %s)", (dept_id, name))
    return dept_id


def dept_for_code(code):
    prefix = code.split()[0]
    mapping = {
        "CSCI": "Mathematics and Computer Science",
        "MATH": "Mathematics and Computer Science",
        "STAT": "Mathematics and Computer Science",
        "ECON": "Economics and Finance",
        "FINC": "Economics and Finance",
        "BIOL": "Biology",
        "CHEM": "Chemistry",
        "ENGL": "English",
        "WRIT": "English",
        "HIST": "History",
        "POLS": "Politics",
        "PSYC": "Psychology",
        "RELG": "Religious Studies",
        "SPAN": "Spanish and Italian",
        "FREN": "French and French Studies",
        "GRMN": "German and German Studies",
        "RUSS": "Russian",
        "ART": "Art, Art History, and Visual Studies",
        "ARTH": "Art, Art History, and Visual Studies",
        "MUSC": "Music",
        "THTR": "Theatre and Dance",
        "DANC": "Theatre and Dance",
        "PHYS": "Physics and Astronomy",
        "ASTR": "Physics and Astronomy",
        "ANTH": "Anthropology",
        "ENST": "Environmental Studies",
        "EES": "Earth and Environmental Systems",
        "ESCI": "Earth and Environmental Systems",
        "FORS": "Forestry",
        "NRSC": "Natural Resources",
        "NEUR": "Neuroscience",
        "WGST": "Women's and Gender Studies",
        "AMST": "American Studies",
        "ASIA": "Asian Studies",
        "CLST": "Classics",
        "GREK": "Classics",
        "LATN": "Classics",
        "HUMN": "Humanities",
        "IGS":  "International and Global Studies",
        "ITAL": "Spanish and Italian",
        "LALS": "Latin American and Latinx Studies",
        "MEMS": "Medieval and Early Modern Studies",
        "PHIL": "Philosophy",
        "RHET": "Rhetoric",
        "AFST": "African and African American Studies",
        "CHIN": "Chinese Studies",
        "BUSI": "Business",
        "FILM": "Film Studies",
        "SAST": "Southern Appalachian Studies",
	"GEOL": "Earth and Environmental Systems",
	"GLBL": "International and Global Studies",
	"INGS": "International and Global Studies",
	"MHUM": "Humanities",
	"NOND": "Interdisciplinary Studies",
	"RUSN": "Russian",
	"THEO": "Religious Studies",
	"WMST": "Women's and Gender Studies",
	"CEMT": "Civic and Global Leadership",
    }
    return mapping.get(prefix, f"Course prefix {prefix}")


def get_or_create_course(cur, code, title, url):
    cur.execute("select course_id from courses where course_code = %s", (code,))
    row = cur.fetchone()
    if row:
        if title != "See catalog page":
            cur.execute(
                "update courses set course_title = %s, catalog_url = %s where course_id = %s",
                (title, url, row[0]),
            )
        return row[0]

    dept_id = get_or_create_department(cur, dept_for_code(code))
    cur.execute("select coalesce(max(course_id), 0) + 1 from courses")
    course_id = cur.fetchone()[0]

    cur.execute("""
        insert into courses
            (course_id, department_id, course_code, course_title, semester_hours, catalog_url)
        values
            (%s, %s, %s, %s, 4, %s)
    """, (course_id, dept_id, code, title, url))

    return course_id


def get_or_create_program(cur, name, kind, url):
    if kind == "major":
        table = "majors"
        id_col = "major_id"
        name_col = "major_name"
    else:
        table = "minors"
        id_col = "minor_id"
        name_col = "minor_name"

    cur.execute(f"select {id_col} from {table} where {name_col} = %s", (name,))
    row = cur.fetchone()
    if row:
        cur.execute(f"update {table} set catalog_url = %s where {id_col} = %s", (url, row[0]))
        return row[0]

    dept_id = get_or_create_department(cur, "Catalog-loaded programs and courses")
    cur.execute(f"select coalesce(max({id_col}), 0) + 1 from {table}")
    program_id = cur.fetchone()[0]

    cur.execute(f"""
        insert into {table}
            ({id_col}, department_id, {name_col}, catalog_url)
        values
            (%s, %s, %s, %s)
    """, (program_id, dept_id, name, url))

    return program_id


def requirement_exists(cur, kind, program_id, course_id):
    if kind == "major":
        table = "major_requirements"
        id_col = "major_id"
    else:
        table = "minor_requirements"
        id_col = "minor_id"

    cur.execute(
        f"select requirement_id from {table} where {id_col} = %s and course_id = %s limit 1",
        (program_id, course_id),
    )
    return cur.fetchone() is not None


def insert_requirement(cur, kind, program_id, course_id, requirement_type, program_name, url):
    if kind == "major":
        table = "major_requirements"
        id_col = "major_id"
    else:
        table = "minor_requirements"
        id_col = "minor_id"

    if requirement_exists(cur, kind, program_id, course_id):
        if requirement_type == "core":
            cur.execute(
                f"""
                update {table}
                set requirement_type = 'core',
                    notes = %s
                where {id_col} = %s and course_id = %s
                """,
                (f"Updated from official catalog page: {url}", program_id, course_id),
            )
        return False

    cur.execute(f"select coalesce(max(requirement_id), 0) + 1 from {table}")
    requirement_id = cur.fetchone()[0]

    cur.execute(f"""
        insert into {table}
            (requirement_id, {id_col}, course_id, requirement_type, requirement_group, notes)
        values
            (%s, %s, %s, %s, %s, %s)
    """, (
        requirement_id,
        program_id,
        course_id,
        requirement_type,
        f"Catalog-scraped requirement for {program_name}",
        f"Loaded from official catalog page: {url}",
    ))

    return True


def count_loaded_requirements(cur, program_name, kind):
    if kind == "major":
        cur.execute("""
            select count(*)
            from majors m
            join major_requirements mr on mr.major_id = m.major_id
            where m.major_name = %s
        """, (program_name,))
    else:
        cur.execute("""
            select count(*)
            from minors n
            join minor_requirements nr on nr.minor_id = n.minor_id
            where n.minor_name = %s
        """, (program_name,))

    return cur.fetchone()[0]


def main():
    programs = load_program_url_list()
    print(f"Loaded {len(programs)} major/minor URLs from program_urls_used.txt.")

    db = get_db()
    cur = db.cursor()

    report = []
    total_inserted = 0

    for index, (name, kind, url) in enumerate(programs, start=1):
        print(f"[{index}/{len(programs)}] {name}")
        print(f"  {url}")

        try:
            program_id = get_or_create_program(cur, name, kind, url)
            rows = scrape_program_courses(name, kind, url)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            print(f"  ERROR: {exc}")
            report.append((name, kind, 0, 0, "ERROR", str(exc), url))
            continue

        inserted = 0
        for code, title, requirement_type in rows:
            course_id = get_or_create_course(cur, code, title, url)
            if insert_requirement(cur, kind, program_id, course_id, requirement_type, name, url):
                inserted += 1

        db.commit()
        total_inserted += inserted

        status = "OK" if rows else "NO_REQUIREMENTS_FOUND"
        report.append((name, kind, len(rows), inserted, status, "", url))
        print(f"  scraped {len(rows)} course row(s); inserted {inserted} new row(s)")
        time.sleep(SLEEP_SECONDS)

    validation_lines = []
    for program_name, minimum in VALIDATION_MIN_ROWS.items():
        kind = "major" if program_name.endswith("Major") else "minor"
        loaded = count_loaded_requirements(cur, program_name, kind)
        status = "OK" if loaded >= minimum else "CHECK"
        validation_lines.append((program_name, loaded, minimum, status))

    db.close()

    with open("catalog_loader_report.txt", "w", encoding="utf-8") as report_file:
        report_file.write("Sewanee PathCheck catalog loader report:\n\n")

        for name, kind, scraped, inserted, status, message, url in report:
            report_file.write(f"{name} ({kind})\n")
            report_file.write(f"  status: {status}\n")
            report_file.write(f"  scraped course rows: {scraped}\n")
            report_file.write(f"  inserted new rows: {inserted}\n")
            report_file.write(f"  source: {url}\n")
            if message:
                report_file.write(f"  message: {message}\n")
            report_file.write("\n")

        report_file.write("\nValidation checks\n")
        report_file.write("-----------------\n")
        for program_name, loaded, minimum, status in validation_lines:
            report_file.write(
                f"{status}: {program_name}: {loaded} rows loaded "
                f"(expected at least {minimum})\n"
            )

    print("\nDone.")
    print(f"Total new requirement rows inserted: {total_inserted}")
    print("Report written to catalog_loader_report.txt")
    print("\nValidation summary:")
    for program_name, loaded, minimum, status in validation_lines:
        print(f"  {status}: {program_name}: {loaded} rows loaded (expected at least {minimum})")


if __name__ == "__main__":
    main()
