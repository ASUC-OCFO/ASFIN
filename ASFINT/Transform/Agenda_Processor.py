import numpy as np
import pandas as pd
import re
from datetime import datetime

from ASFINT.Utility.Cleaning import in_df, is_type
from ASFINT.Utility.Utils import column_converter

def _find_chunk_pattern(starts, ends, end_prepattern = r'\d+\s'):
      r"""Build a regex that captures text between configured section headings.

      ``starts`` contains accepted opening headings and ``ends`` contains accepted
      closing headings. ``end_prepattern`` is prepended to each closing heading so
      numbered-list markers can be included in the boundary pattern.
      """
      assert len(starts) != 0, 'starts is an empty list'
      assert is_type(starts, str), 'starts is not a list of strings'
      assert len(ends) != 0, 'ends is an empty list'
      assert is_type(ends, str), 'ends is not a list of strings'

      assert isinstance(end_prepattern, str), f'end_prepattern should be a string but is type {type(end_prepattern)}'
      
      pattern = ''
      if len(starts) == 1:
          pattern += starts[0]
      else: 
         pattern = '(?:'
         for start_keyword in starts[:-1]: 
            pattern += start_keyword + '|'
         pattern += starts[-1] + ')'
      
      pattern += r'\s*?([\s\S]*?)(?:'  # Use non-greedy matching between boundaries.

      if len(ends) == 1:
         pattern += ends[0]
      else: 
         for end_keyword in ends[:-1]: 
            pattern += end_prepattern + end_keyword + '|'
         pattern += end_prepattern + ends[-1]

      pattern += ')'
      return pattern

def _motion_processor(club_names, names_and_motions):
   """Map each organization in a section to the motion lines that follow it.

   Repeated organization names receive a numeric suffix so separate requests remain
   distinct. Lines before the first organization are reported and skipped.
   """
   rv = {}
   repeats = dict(zip(club_names, [0]*len(club_names)))
   club_set = set(club_names)  
   curr_club = None
   for curr in names_and_motions: 
      if curr in club_set: 
         if curr in rv:  # Keep repeated requests separate.
            curr_club = curr + f" ({str(repeats[curr] + 1)})"
         else:
            curr_club = curr
         rv[curr_club] = []  # Preserve requests with no recorded motion.
      else: 
         if curr_club is None:
            print(f"""WARNING line skip occurred with line: {curr}
            total list is: {names_and_motions}""")
         else:
            rv[curr_club].append(curr)

   return rv

def inpt_cleaner(inpt: str):
   inpt = re.sub(r"\(\$?\d+,?\d*\.?\d*\)", "", inpt)
   # Numbered-list periods are removed by Agenda_Processor before this helper runs.
   return inpt

def _process_2020_nested_format(inpt: str, date: str, debug=True):
   """Process legacy agendas with request sections nested under Pending Business.

   This format appears in 2020/2021 files and may contain an additional Finance
   Resolution subsection between Pending Business and the request sections.
   """
   if debug:
      print("Attempting to process as 2020/2021 nested format...")

   # Map legacy section labels to canonical request types.
   section_map = {
      'Sponsorship': 'Sponsorship',
      'Senate Contingency Funding': 'Contingency',
      'Contingency Funding': 'Contingency',
      'Contingency': 'Contingency',
      'Funding': 'Contingency',
      'Space Reservation': 'Space Reservation',
      'Finance Rule Waiver': 'Finance Rule',
      'Finance Rule': 'Finance Rule',
      'Rule Waiver': 'Rule Waiver',
      'ABSA Appeals': 'ABSA Appeals'
   }

   list_of_dfs = []

   # Isolate the Pending Business section before parsing nested request sections.
   pending_pattern = r'Pending Business.*?(?=\d+\s+Adjournment|\d+\s+Guest|$)'
   pending_match = re.search(pending_pattern, inpt, re.DOTALL | re.IGNORECASE)

   if not pending_match:
      if debug:
         print("No Pending Business section found")
      return None

   pending_section = pending_match.group(0)
   if debug:
      print(f"Found Pending Business section (length: {len(pending_section)})")

   # Some legacy files add a Finance Resolution subsection around the request sections.
   fr_pattern = r'\d+\s+FR \d+/\d+ S\d+\s*\n(.*?)(?=\n\s{0,3}\d+\s+[A-Z]|$)'
   fr_match = re.search(fr_pattern, pending_section, re.DOTALL | re.IGNORECASE)
   if fr_match:
      # Parse request sections from the nested Finance Resolution subsection.
      pending_section = fr_match.group(1)
      if debug:
         print(f"Found FR subsection, using it instead (length: {len(pending_section)})")

   # Process each recognized request section.
   for section_name, request_type in section_map.items():
      # Capture the section until the next recognized section at the same nesting level.
      other_sections = '|'.join([re.escape(s) for s in section_map.keys() if s != section_name])
      section_pattern = rf'(\d+)\s+{re.escape(section_name)}\s*\n(.*?)(?=\n\s{{0,8}}\d+\s+(?:{other_sections})|$)'
      section_match = re.search(section_pattern, pending_section, re.DOTALL | re.IGNORECASE)

      if not section_match:
         continue

      section_content = section_match.group(2)  # Group 1 contains the section number.
      if debug:
         print(f"\nFound section: {section_name}")
         print(f"Section content preview: {section_content[:200]}...")

      # Organization entries are less indented than their motion lines.
      orgs = []
      org_contents = {}
      org_counts = {}  # Keep repeated organization entries distinct.

      lines = section_content.split('\n')
      current_org = None
      current_org_indent = 0

      for line in lines:
         # Accept organization entries from either supported legacy nesting depth.
         org_match = re.match(r'^\s{6,10}(\d+)\s+(.+)', line)
         if org_match:
            indent = len(line) - len(line.lstrip())
            org_name = org_match.group(2).strip()

            # Exclude procedural lines from organization entries.
            if not re.match(r'(Motion|Second|Senator.*motions?\s+to\s+(pass|send)\s+FR)', org_name, re.IGNORECASE):
               # Append a count when the same organization has multiple requests.
               if org_name in org_counts:
                  org_counts[org_name] += 1
                  current_org = f"{org_name} ({org_counts[org_name]})"
               else:
                  org_counts[org_name] = 0
                  current_org = org_name

               current_org_indent = indent
               orgs.append(current_org)
               org_contents[current_org] = []
               if debug:
                  print(f"  Found org: {current_org}")
         elif current_org and line.strip():
            # Deeper-indented lines belong to the current organization.
            indent = len(line) - len(line.lstrip())
            if indent > current_org_indent:
               org_contents[current_org].append(line.strip())

      # Derive committee decisions and allocations from each organization's motion text.
      decisions = []
      allocations = []

      for org_name in orgs:
         motions = org_contents.get(org_name, [])
         sub_motions = " ".join(motions)

         if debug:
            print(f"  {org_name}: {sub_motions[:100]}")

         # Determine the committee decision.
         if re.search(r'(tabled?\sindefinetly)|(tabled?\sindefinitely)|(table\sindefinitely)|(deny)|not present.*tabled', sub_motions, re.IGNORECASE):
            decisions.append('Denied or Tabled Indefinetly')
            allocations.append(0)
         elif re.search(r'(tabled?\suntil)|(tabled?\sfor)|(tabled?\sto)|(table\sto)|(tabled to next week)|not present.*tabled', sub_motions, re.IGNORECASE):
            decisions.append('Tabled')
            allocations.append(0)
         elif re.search(r'(motion\s+(passes|passed|approved))|(motions?\s+to\s+(sponsor|approve|amend))', sub_motions, re.IGNORECASE):
            # Legacy motions use several approval and allocation phrasings.

            # Only treat a motion as approved when the record indicates it passed.
            if re.search(r'motion\s+(passed|approved)', sub_motions, re.IGNORECASE):
               # Extract an allocation from the supported legacy motion phrasings.
               # Finance-rule waiver amount.
               waiver_amount = re.findall(r'waiver\s+for\s+\$?(\d+(?:,\d+)?(?:\.\d+)?)', sub_motions, re.IGNORECASE)
               # Explicit allocation amount.
               allocate_amount = re.findall(r'allocate\s+\$?(\d+(?:,\d+)?(?:\.\d+)?)', sub_motions, re.IGNORECASE)
               # Direct approval amount, with or without a dollar sign.
               approve_amount = re.findall(r'approve\s+(?:for\s+)?\$?(\d+(?:,\d+)?(?:\.\d+)?)', sub_motions, re.IGNORECASE)

               if waiver_amount:
                  decisions.append('Approved')
                  allocations.append(waiver_amount[0])
               elif allocate_amount:
                  decisions.append('Approved')
                  allocations.append(allocate_amount[0])
               elif approve_amount:
                  decisions.append('Approved')
                  allocations.append(approve_amount[0])
               else:
                  # Approved motion with no recorded dollar amount.
                  decisions.append('Approved')
                  allocations.append(np.nan)
            else:
               # Motion text is present but does not indicate passage.
               decisions.append('ERROR could not find conclusive motion')
               allocations.append(np.nan)
         elif not sub_motions:
            decisions.append('No record on input doc')
            allocations.append(np.nan)
         else:
            decisions.append('ERROR could not find conclusive motion')
            allocations.append(np.nan)

      if orgs:
         df = pd.DataFrame({
            'Org Name': pd.Series(orgs).str.strip(),
            'Request Type': [request_type] * len(orgs),
            'Committee Status': decisions,
            'Amount': allocations,
            'Date': [date] * len(orgs),
         })
         list_of_dfs.append(df)
         if debug:
            print(f"Created DataFrame for {section_name} with {len(orgs)} organizations")

   if list_of_dfs:
      result = pd.concat(list_of_dfs, ignore_index=True)
      return result

   return None


def Agenda_Processor(inpt: str,
                     start=['Contingency', 'Finance Rule', 'Rule Waiver', 'Space Reservation'],
                     end=['Finance Rule', 'Rule Waiver', 'Space Reservation', 'Sponsorship', 'Adjournment', 'ABSA', 'ABSA Appeals'],
                     identifier=r'(?:\w+,\s)?(\w+\s\d{1,2}\w*,\s\d{4})',
                     date_format="%m/%d/%Y",
                     debug=True):
   """
   Processes agenda documents to extract funding information.
   Handles both modern format (flat sections) and 2020 format (nested under Pending Business).

   input (str): The raw text of the agenda to be processed. Usually a .txt file
   identifier (str): Regex pattern to extract a certain piece of text from inpt as the identifier for the chunk extracted from inpt
   """
   # Remove periods from numbered-list markers without altering decimal amounts.
   inpt = re.sub(r'(\d+)\.(\s)', r'\1\2', inpt)

   date_match = re.findall(rf"{identifier}", inpt)
   if not date_match:
      print(f"Agenda_Processor could not find date on agenda doc")
      date = "00/00/0000"
   else:
      date_str = date_match[0]  # the matched date string
      dt = pd.to_datetime(date_str, errors='coerce')  # parse string into timestamp object
      date = dt.strftime(date_format)
   # Route legacy nested agendas directly to the nested-format parser.
   has_pending_business = re.search(r'Pending Business', inpt, re.IGNORECASE)
   has_nested_sections = re.search(r'Pending Business.*?(Contingency Funding|Senate Contingency Funding|Finance Rule Waiver)', inpt, re.DOTALL | re.IGNORECASE)

   # Map each start section to the valid sections that can follow it.
   start_end_dict = {}
   for i in range(len(start)):
      start_end_dict[start[i]] = end[i:]
   list_of_dfs = []
   rv = None

   # Use only one parsing path for a document.
   if has_pending_business and has_nested_sections:
      if debug:
         print("Detected nested format (2020/2021), skipping modern format processing")
   else:
      for s in start_end_dict:
         if re.findall(rf"\d+\s{s}", inpt):


            pattern = _find_chunk_pattern(starts = [s], ends = start_end_dict[s])
            if debug:
               print(f"Agenda Processor Pattern: {pattern}")

            chunk = re.findall(rf"{pattern}", inpt)[0]
            chunk = inpt_cleaner(chunk)
            print(f"chunk: {chunk}")

            # Explicit punctuation support prevents valid organization-name characters from truncating matches.
            valid_name_chars = r'\w\s\-\_\*\&\%\$\+\#\@\!\(\)\,\'\"\[\]\.:'
            club_name_pattern = rf'\d+\s(?!Motion|Seconded)([{valid_name_chars}]+?)(?=\n)'
            club_names = list(re.findall(club_name_pattern, chunk))
            if debug:
               print(f"Agenda Processor Club Names: {club_names}")

            names_and_motions = list(re.findall(rf'\d+\s(.+)\n?', chunk))
            motion_dict = _motion_processor(club_names, names_and_motions)
            if debug:
               print(f"Agenda Processor Motion Dict: {motion_dict}")


            decisions = []
            allocations = []
            for name in motion_dict.keys():

               if motion_dict[name] == []:
                  decisions.append('No record on input doc')
                  allocations.append(np.nan)

               else:
                  sub_motions = " ".join(motion_dict[name])
                  print(f'sub-motions: {sub_motions}')

                  # Resolve conflicting motion text conservatively: denial, tabling, approval, then no decision.
                  if re.findall(r'(tabled?\sindefinetly)|(tabled?\sindefinitely)|(deny)', sub_motions) != []:
                     decisions.append('Denied or Tabled Indefinetly')
                     allocations.append(0)
                  # Check for temporary tabling.
                  elif re.findall(r'(tabled?\suntil)|(tabled?\sfor)|(tabled?\sto)', sub_motions) != []:
                     decisions.append('Tabled')
                     allocations.append(0)
                  # Check for approval and an optional allocation amount.
                  elif re.findall(r'[aA]pprove', sub_motions) != []:
                     # Check partial approval before the more general approval pattern.
                     partial_match = re.findall(r'[pP]artially\s+[aA]pprove\s+(?:for\s+)?\$?(\d+(?:,\d+)?(?:\.\d+)?)', sub_motions)
                     # Check for a regular approval amount.
                     dollar_amount = re.findall(r'[aA]pprove\s+(?:for\s+)?\$?(\d+(?:,\d+)?(?:\.\d+)?)', sub_motions)

                     if partial_match != []:
                        # Use the amount attached to the partial-approval motion.
                        decisions.append('Partially Approved')
                        allocations.append(partial_match[0])
                     elif dollar_amount != []:
                        decisions.append('Approved')
                        allocations.append(dollar_amount[0])
                     else:
                        decisions.append('Approved but dollar amount not listed')
                        allocations.append(np.nan)
                  # Preserve requests with no recorded committee decision.
                  elif sub_motions == '':
                     decisions.append('No record on input doc')
                     allocations.append(np.nan)
                  else:
                     decisions.append('ERROR could not find conclusive motion')
                     allocations.append(np.nan)

            rv = pd.DataFrame({
               'Org Name' : pd.Series(motion_dict.keys()).str.strip(),
               "Request Type": [s] * len(allocations),
               'Committee Status' : decisions,
               'Amount' : allocations,
               'Date' : [date]*len(allocations),
               }
            )

            list_of_dfs.append(rv)

   # Fall back to the legacy nested parser when the modern section scan finds no rows.
   if not list_of_dfs:
      if debug:
         print(f"Agenda Processor: No matching sections found in modern format")
         print(f"Attempting 2020 nested format processing...")

      # Attempt the legacy nested format.
      rv = _process_2020_nested_format(inpt, date, debug=debug)

      if rv is None or rv.empty:
         if debug:
            print(f"Agenda Processor: No data found in any format")
         rv = pd.DataFrame(columns=['Org Name', 'Request Type', 'Committee Status', 'Amount', 'Date'])
      else:
         if debug:
            print(f"Successfully processed using 2020 nested format: {len(rv)} organizations found")
   else:
      if debug:
         print(f"Agenda Processor Final df: {rv}")
      rv = pd.concat(list_of_dfs)

   # Normalize trailing markup in organization names.
   if not rv.empty:
      rv["Org Name"] = rv["Org Name"].str.replace("*", "", regex=False)
      rv["Org Name"] = rv["Org Name"].str.replace(r',\s*$', '', regex=True)
      rv["Org Name"] = rv["Org Name"].str.strip()

   return rv, date


# Direct DOCX processing for the current Finance Committee pipeline.
AGENDA_COLUMNS = ["Org Name", "Request Type", "Committee Status", "Amount", "Date"]

_DOCX_SECTION_MAP = {
    "contingency": "Contingency",
    "contingency funding": "Contingency",
    "senate contingency funding": "Contingency",
    "finance rule": "Finance Rule",
    "finance rule waiver": "Finance Rule",
    "rule waiver": "Finance Rule",
    "space reservation": "Space Reservation",
    "sponsorship": "Sponsorship",
    "absa budget appeal": "ABSA Budget Appeals",
    "absa budget appeals": "ABSA Budget Appeals",
    "absa appeals": "ABSA Budget Appeals",
    "senate bill": "Senate Bill",
    "senate bills": "Senate Bill",
    "senate resolution": "Senate Bill",
    "senate resolutions": "Senate Bill",
}
_DOCX_END_SECTIONS = {
    "adjournment",
    "final roll call",
    "guest announcements & public comment",
    "guest announcements and public comment",
    "public comment",
    "new business",
}
_DOCX_CLOSING_PREFIXES = (
    "motion to enter closed",
    "motion to exit closed",
    "approve items as allocated",
    "motion to adjourn",
    "adjournment",
)


def _docx_compact(value):
    import re
    return re.sub(r"\s+", " ", str(value or "").strip())


def _docx_clean_org(value: str) -> str:
    import re
    value = _docx_compact(value)
    value = re.sub(r"\s+from\s+Senator\b.*?\bSeconded\s+by\s+Senator\b.*$", "", value, flags=re.I).strip()
    value = re.sub(r"\s*\*+\s*$", "", value).strip()
    value = re.sub(r"\s*\(\s*\$?\s*[\d,]+(?:\.\d+)?\s*\)\s*$", "", value).strip()
    return re.sub(r",\s*$", "", value).strip()


def _docx_is_motion(line: str) -> bool:
    import re
    low = line.lower().strip()
    return bool(
        re.match(r"^[a-z]\.?\s+motion\b", low)
        or re.match(r"^motion\b", low)
        or re.match(r"^seconded\b", low)
        or re.search(r"\b(?:senator|cfo)\b.*\b(?:move|moves|moved|motions)\s+to\b", low)
    )


def _docx_paragraph_level(paragraph):
    """Return the DOCX list level for a paragraph, or None if it is not numbered."""
    ppr = paragraph._p.pPr
    numpr = ppr.numPr if ppr is not None else None
    if numpr is None or numpr.ilvl is None:
        return None
    return int(numpr.ilvl.val)


def _docx_decision(motions):
    import re
    import numpy as np

    if not motions:
        return "No record on input doc", np.nan
    text = " ".join(motions)
    low = text.lower()
    if re.search(r"table\w*\s+indefinit", low):
        return "Tabled Indefinitely", 0
    if re.search(r"\bdeny\b|\bdenied\b", low):
        return "Denied", 0
    if re.search(r"table\w*\s+(?:until|for|to)|table\s+to|next\s+(?:week|meeting)|\btable(?:d)?\b", low):
        return "Tabled", 0

    omitted = re.search(r"\bmotion\s+to\s+\$?\s*([\d,]+(?:\.\d+)?)", text, re.I)
    if omitted:
        return "Approved", omitted.group(1).replace(",", "")
    partial = re.search(r"partially\s+approve\s+(?:for\s+)?\$?\s*([\d,]+(?:\.\d+)?)", text, re.I)
    if partial:
        return "Partially Approved", partial.group(1).replace(",", "")
    amount = re.search(r"\bapprove\b\s+(?:for\s+)?\$?\s*([\d,]+(?:\.\d+)?)", text, re.I)
    if not amount:
        amount = re.search(r"\bapprove\b[^$\d]{0,30}\$\s*([\d,]+(?:\.\d+)?)", text, re.I)
    if re.search(r"\bapprove\b|\bapproved\b", text, re.I):
        return ("Approved", amount.group(1).replace(",", "")) if amount else ("Approved but dollar amount not listed", np.nan)
    if re.search(r"\bforward(?:ed)?\b.*\bsenate\b", text, re.I):
        return "Forwarded to Senate", np.nan
    return "ERROR could not find conclusive motion", np.nan


def _docx_scalar_decision(line: str):
    import re
    import numpy as np

    text = _docx_compact(line)
    low = text.lower()
    numeric = re.fullmatch(r"\$?\s*([\d,]+(?:\.\d+)?)", text)
    if numeric:
        return "Approved", numeric.group(1).replace(",", "")
    if re.fullmatch(r"denied?", low):
        return "Denied", 0
    if re.fullmatch(r"table\w*\s+indefinit\w*", low):
        return "Tabled Indefinitely", 0
    if re.fullmatch(r"table(?:d)?(?:\s+for\s+(?:one|a)\s+week)?", low):
        return "Tabled", 0
    if re.fullmatch(r"approved?(?:\s+as\s+amended)?", low):
        return "Approved but dollar amount not listed", np.nan
    return None


def _docx_embedded_week(paragraphs):
    import re
    for line in paragraphs:
        match = re.search(r"\bFR\s*\d{2}\s*/\s*\d{2}\s+([FS]\s*0*\d+)\b", line, re.I)
        if match:
            week = re.search(r"([FS])\s*0*(\d+)", match.group(1), re.I)
            if week:
                return f"{week.group(1).upper()}{int(week.group(2))}"
    return None


def _docx_embedded_date(paragraphs):
    import re
    from datetime import datetime
    months = "January|February|March|April|May|June|July|August|September|October|November|December"
    pattern = rf"\b({months})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,\s*(20\d{{2}})\b"
    for line in paragraphs[:12]:
        match = re.search(pattern, line, re.I)
        if match:
            try:
                return datetime.strptime(f"{match.group(1)} {match.group(2)} {match.group(3)}", "%B %d %Y").strftime("%Y-%m-%d")
            except ValueError:
                pass
    return None


def _docx_senate_bill(line: str):
    """Return an SR title embedded in a line, if present."""
    import re

    text = _docx_compact(line)
    match = re.search(r"\bSR\s*\d{2}\s*/\s*\d{2}\s*[- ]?\s*\d{3}\b", text, re.I)
    if not match:
        return None
    value = text[match.start():]
    value = re.split(r"\s+(?:from|by)\s+Senator\b|\.\s*Seconded\b", value, maxsplit=1, flags=re.I)[0]
    return value.strip().rstrip(".")


def Agenda_Docx_Processor(path, meeting_date: str):
    """Clean one modern Finance Committee agenda directly from DOCX."""
    from docx import Document
    import pandas as pd

    document = Document(path)
    records = []
    for paragraph in document.paragraphs:
        text = _docx_compact(paragraph.text)
        if text:
            records.append((text, _docx_paragraph_level(paragraph)))

    paragraph_text = [text for text, _ in records]
    embedded_week = _docx_embedded_week(paragraph_text)
    embedded_date = _docx_embedded_date(paragraph_text)
    canonical_date = pd.Timestamp(meeting_date).strftime("%m/%d/%Y")

    rows = []
    flags = []
    section = None
    section_level = None
    current_org = None
    motions = []
    current_decision = None
    in_pending_business = False

    def flush():
        nonlocal current_org, motions, current_decision
        if section and current_org:
            status, amount = current_decision if current_decision is not None else _docx_decision(motions)
            rows.append({
                "Org Name": _docx_clean_org(current_org),
                "Request Type": section,
                "Committee Status": status,
                "Amount": amount,
                "Date": canonical_date,
            })
        current_org = None
        motions = []
        current_decision = None

    for raw_line, level in records:
        line = _docx_compact(raw_line)
        low = line.lower().strip().rstrip(":")

        if low in _DOCX_SECTION_MAP:
            flush()
            section = _DOCX_SECTION_MAP[low]
            section_level = level
            continue

        if section and any(low.startswith(prefix) for prefix in _DOCX_CLOSING_PREFIXES):
            flush()
            section = None
            section_level = None
            break

        if section and any(low.startswith(end) for end in _DOCX_END_SECTIONS):
            flush()
            section = None
            section_level = None
            continue

        if low in {"pending business", "finance rule (all approved)"}:
            if low == "pending business":
                in_pending_business = True
            if low.startswith("finance rule"):
                flush()
                section = "Finance Rule"
                section_level = level
            continue

        if re.match(r"^FR\s+\d", line, re.I):
            continue

        senate_bill = _docx_senate_bill(line)
        add_senate_bill = bool(
            senate_bill
            and in_pending_business
            and _docx_is_motion(line)
            and re.search(r"\b(?:add|amend)\b", low)
        )
        if add_senate_bill or (senate_bill and re.match(r"^SR\s+\d", line, re.I)):
            flush()
            section = "Senate Bill"
            section_level = (level - 1) if level is not None and level > 0 else None
            current_org = senate_bill
            continue

        if not section:
            continue

        # Request sections and request items are numbered lists. Only direct children
        # of a recognized section can create request rows; other prose is discussion.
        is_direct_item = (
            section_level is not None
            and level is not None
            and level == section_level + 1
        )

        if section == "Senate Bill":
            if senate_bill and (is_direct_item or re.match(r"^SR\s+\d", line, re.I)):
                flush()
                current_org = senate_bill
                continue

            scalar = _docx_scalar_decision(line)
            if scalar is not None and current_org is not None:
                current_decision = scalar
                continue

            if _docx_is_motion(line) and current_org is not None:
                motions.append(line)
                continue

            # Ignore unstructured discussion under the current Senate Bill.
            continue

        if _docx_is_motion(line):
            if current_org is not None:
                motions.append(line)
            continue

        scalar = _docx_scalar_decision(line)
        if scalar is not None and current_org is not None:
            if current_decision is None:
                current_decision = scalar
            else:
                numeric = re.fullmatch(r"\$?\s*([\d,]+(?:\.\d+)?)", line)
                status, _ = current_decision
                if numeric and status == "Approved but dollar amount not listed":
                    current_decision = ("Approved", numeric.group(1).replace(",", ""))
                elif numeric and status in {"Denied", "Tabled", "Tabled Indefinitely"}:
                    # Ignore trailing numeric reference data after a conclusive non-approval.
                    pass
                else:
                    flags.append({
                        "severity": "warning",
                        "code": "AGENDA_EXTRA_SCALAR",
                        "message": f"Extra outcome value after {current_org}",
                        "source": "Agenda",
                        "details": line,
                    })
            continue

        if is_direct_item:
            flush()
            current_org = line
            continue

        # Inputs without Word list metadata use a conservative section/request/motion
        # fallback. After a request starts, free-form prose cannot create another row.
        if section_level is None and level is None and current_org is None:
            current_org = line

    flush()
    out = pd.DataFrame(rows, columns=AGENDA_COLUMNS)
    if not out.empty:
        for _, row in out[out["Committee Status"] == "ERROR could not find conclusive motion"].iterrows():
            flags.append({
                "severity": "warning",
                "code": "AGENDA_UNRESOLVED_MOTION",
                "message": f"Could not determine committee decision for {row['Org Name']}",
                "source": "Agenda",
                "details": "",
            })
    return out, embedded_week, embedded_date, flags


def Agenda_Docx_Metadata(path):
    """Return (week, embedded_date) from a Finance Committee DOCX."""
    from docx import Document
    paragraphs = [_docx_compact(p.text) for p in Document(path).paragraphs if _docx_compact(p.text)]
    return _docx_embedded_week(paragraphs), _docx_embedded_date(paragraphs)
