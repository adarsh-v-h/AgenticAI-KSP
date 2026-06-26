import sys
import os
import asyncio
import random
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

# Set random seed for deterministic synthetic data generation
random.seed(42)

# Ensure backend root is in sys.path
backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.append(backend_path)

# Set DB_NAME to DB_NAME_v2 dynamically at runtime
load_dotenv()
db_name = os.getenv("DB_NAME", "ksp_crime_db")
if not db_name.endswith("_v2"):
    db_name = f"{db_name}_v2"
os.environ["DB_NAME"] = db_name

from db.connection import create_pool, close_pool

LOCATIONS = [
    {"name": "Koramangala", "prefix": "KOR", "lat": 12.9352, "lng": 77.6244},
    {"name": "Indiranagar", "prefix": "IND", "lat": 12.9719, "lng": 77.6412},
    {"name": "Jayanagar", "prefix": "JAY", "lat": 12.9308, "lng": 77.5838},
    {"name": "Shivajinagar", "prefix": "SHI", "lat": 12.9857, "lng": 77.5971},
    {"name": "Yeshwanthpur", "prefix": "YES", "lat": 13.0270, "lng": 77.5409},
    {"name": "Malleshwaram", "prefix": "MAL", "lat": 13.0031, "lng": 77.5696},
    {"name": "Whitefield", "prefix": "WHI", "lat": 12.9698, "lng": 77.7500},
    {"name": "Electronic City", "prefix": "ECE", "lat": 12.8452, "lng": 77.6602},
    {"name": "Hebbal", "prefix": "HEB", "lat": 13.0359, "lng": 77.5970},
    {"name": "Rajajinagar", "prefix": "RAJ", "lat": 12.9882, "lng": 77.5548},
    {"name": "BTM Layout", "prefix": "BTM", "lat": 12.9166, "lng": 77.6101},
    {"name": "JP Nagar", "prefix": "JPN", "lat": 12.9063, "lng": 77.5857},
    {"name": "HSR Layout", "prefix": "HSR", "lat": 12.9103, "lng": 77.6450},
    {"name": "Marathahalli", "prefix": "MAR", "lat": 12.9562, "lng": 77.6967},
    {"name": "Yelahanka", "prefix": "YEL", "lat": 13.1007, "lng": 77.5963}
]

MOCK_NAMES_MALE = [
    "Karthik", "Suresh", "Pradeep", "Raghav", "Girish", "Anil", "Sunil", "Basavaraj", 
    "Shiva", "Guru", "Abhishek", "Chethan", "Darshan", "Puneeth", "Yash", "Vinay", 
    "Santosh", "Manjunatha", "Ravi", "Mohan", "Kiran", "Nagaraj", "Prakash", "Sanjay"
]

MOCK_NAMES_FEMALE = [
    "Deepa", "Kavitha", "Shruthi", "Roopa", "Anitha", "Sindhu", "Priya", "Jyothi", 
    "Suma", "Lakshmi", "Radha", "Meenakshi", "Divya", "Swathi", "Asha", "Shalini",
    "Saraswathi", "Mamatha", "Geetha", "Nandini", "Shubha", "Bhagya", "Netra"
]

MOCK_SURNAMES = [
    "Gowda", "Kumar", "Shetty", "Rao", "Nayak", "Patil", "Hegde", "Reddy", "Murthy", 
    "Raju", "Bhat", "Raj", "Naik", "Prasad", "Acharya", "Joshi", "Deshpande", "Aradhya"
]

def random_date(start_date: date, end_date: date) -> date:
    time_between = end_date - start_date
    days_between = time_between.days
    random_number_of_days = random.randrange(days_between)
    return start_date + timedelta(days=random_number_of_days)

def random_time() -> str:
    hour = random.randint(0, 23)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    return f"{hour:02d}:{minute:02d}:{second:02d}"

async def seed_lookups(conn):
    async with conn.cursor() as cur:
        # State
        await cur.execute("INSERT INTO State (StateName, NationalityID, Active) VALUES (%s, %s, %s)", ('Karnataka', 1, 1))
        state_id = cur.lastrowid

        # District
        districts = ['Bengaluru Urban', 'Bengaluru Rural', 'Mysuru', 'Mangaluru', 'Hubballi-Dharwad']
        district_ids = []
        for dist in districts:
            await cur.execute("INSERT INTO District (DistrictName, StateID, Active) VALUES (%s, %s, %s)", (dist, state_id, 1))
            district_ids.append(cur.lastrowid)

        # UnitType
        unit_types = [
            ('Police Station', 'City', 1, 1),
            ('Circle Office', 'District', 2, 1),
            ('District Office', 'State', 3, 1)
        ]
        unit_type_ids = []
        for ut in unit_types:
            await cur.execute("INSERT INTO UnitType (UnitTypeName, CityDistState, Hierarchy, Active) VALUES (%s, %s, %s, %s)", ut)
            unit_type_ids.append(cur.lastrowid)

        # Unit (Police Stations in districts)
        units = [
            ('Koramangala PS', unit_type_ids[0], None, 1, state_id, district_ids[0], 1),
            ('Whitefield PS', unit_type_ids[0], None, 1, state_id, district_ids[1], 1),
            ('Mysuru Central PS', unit_type_ids[0], None, 1, state_id, district_ids[2], 1),
            ('Mangaluru City PS', unit_type_ids[0], None, 1, state_id, district_ids[3], 1),
            ('Hubballi PS', unit_type_ids[0], None, 1, state_id, district_ids[4], 1)
        ]
        unit_ids = []
        for unit in units:
            await cur.execute("INSERT INTO Unit (UnitName, TypeID, ParentUnit, NationalityID, StateID, DistrictID, Active) VALUES (%s, %s, %s, %s, %s, %s, %s)", unit)
            unit_ids.append(cur.lastrowid)

        # Court
        courts = [
            ('Bengaluru Urban Court', district_ids[0], state_id, 1),
            ('Bengaluru Rural Court', district_ids[1], state_id, 1),
            ('Mysuru District Court', district_ids[2], state_id, 1),
            ('Mangaluru City Court', district_ids[3], state_id, 1),
            ('Hubballi District Court', district_ids[4], state_id, 1)
        ]
        court_ids = []
        for court in courts:
            await cur.execute("INSERT INTO Court (CourtName, DistrictID, StateID, Active) VALUES (%s, %s, %s, %s)", court)
            court_ids.append(cur.lastrowid)

        # Rank (use backticks for `Rank`)
        ranks = ['Constable', 'Head Constable', 'ASI', 'SI', 'PI', 'Inspector', 'DySP', 'SP']
        rank_ids = {}
        for idx, r in enumerate(ranks):
            await cur.execute("INSERT INTO `Rank` (RankName, Hierarchy, Active) VALUES (%s, %s, %s)", (r, idx + 1, 1))
            rank_ids[r] = cur.lastrowid

        # Designation
        designations = [
            ('Investigating Officer', 1),
            ('SHO', 2),
            ('Beat Officer', 3),
            ('Circle Inspector', 4)
        ]
        designation_ids = {}
        for idx, d in enumerate(designations):
            await cur.execute("INSERT INTO Designation (DesignationName, Active, SortOrder) VALUES (%s, %s, %s)", (d[0], 1, d[1]))
            designation_ids[d[0]] = cur.lastrowid

        # CrimeHead
        heads = [
            'Crimes Against Property',
            'Crimes Against Person',
            'Cyber Crimes',
            'Crimes Against Society'
        ]
        head_ids = []
        for h in heads:
            await cur.execute("INSERT INTO CrimeHead (CrimeGroupName, Active) VALUES (%s, %s)", (h, 1))
            head_ids.append(cur.lastrowid)

        # CrimeSubHead
        subheads = [
            (head_ids[0], 'Theft', 1),
            (head_ids[0], 'Robbery', 2),
            (head_ids[0], 'Vehicle Theft', 3),
            (head_ids[0], 'Fraud', 4),
            (head_ids[1], 'Assault', 1),
            (head_ids[1], 'Murder', 2),
            (head_ids[1], 'Domestic Violence', 3),
            (head_ids[1], 'Missing Person', 4),
            (head_ids[2], 'Phishing', 1),
            (head_ids[2], 'Online Harassment', 2),
            (head_ids[2], 'Identity Theft', 3),
            (head_ids[2], 'Hacking', 4),
            (head_ids[3], 'Drug Offense', 1)
        ]
        subhead_ids = {}
        for sh in subheads:
            await cur.execute("INSERT INTO CrimeSubHead (CrimeHeadID, CrimeHeadName, SeqID) VALUES (%s, %s, %s)", sh)
            subhead_ids[sh[1]] = cur.lastrowid

        # CaseCategory
        categories = ['FIR', 'UDR', 'Zero FIR', 'PAR']
        category_ids = []
        for cat in categories:
            await cur.execute("INSERT INTO CaseCategory (LookupValue) VALUES (%s)", (cat,))
            category_ids.append(cur.lastrowid)

        # GravityOffence
        gravity = ['Heinous', 'Non-Heinous']
        gravity_ids = []
        for grav in gravity:
            await cur.execute("INSERT INTO GravityOffence (LookupValue) VALUES (%s)", (grav,))
            gravity_ids.append(cur.lastrowid)

        # CaseStatusMaster
        statuses = ['Under Investigation', 'Charge Sheeted', 'Closed', 'Open']
        status_ids = {}
        for stat in statuses:
            await cur.execute("INSERT INTO CaseStatusMaster (CaseStatusName) VALUES (%s)", (stat,))
            status_ids[stat] = cur.lastrowid

        # Act
        acts = [
            ('IPC', 'Indian Penal Code', 'IPC', 1),
            ('NDPS', 'Narcotic Drugs and Psychotropic Substances Act', 'NDPS', 1),
            ('IT Act', 'Information Technology Act', 'IT Act', 1)
        ]
        for act in acts:
            await cur.execute("INSERT INTO Act (ActCode, ActDescription, ShortName, Active) VALUES (%s, %s, %s, %s)", act)

        # Section
        sections = [
            ('IPC', '379', 'Theft', 1),
            ('IPC', '302', 'Murder', 1),
            ('IPC', '392', 'Robbery', 1),
            ('IPC', '323', 'Assault', 1),
            ('IPC', '498A', 'Domestic Violence', 1),
            ('NDPS', '20', 'Drug possession/use', 1),
            ('NDPS', '22', 'Drug trafficking', 1),
            ('IT Act', '66C', 'Identity theft', 1),
            ('IT Act', '66D', 'Cheating by impersonation', 1)
        ]
        for sec in sections:
            await cur.execute("INSERT INTO Section (ActCode, SectionCode, SectionDescription, Active) VALUES (%s, %s, %s, %s)", sec)

        # CasteMaster
        castes = ['General', 'OBC', 'SC', 'ST', 'Other']
        caste_ids = []
        for caste in castes:
            await cur.execute("INSERT INTO CasteMaster (caste_master_name) VALUES (%s)", (caste,))
            caste_ids.append(cur.lastrowid)

        # ReligionMaster
        religions = ['Hindu', 'Muslim', 'Christian', 'Sikh', 'Jain', 'Buddhist', 'Other']
        religion_ids = []
        for rel in religions:
            await cur.execute("INSERT INTO ReligionMaster (ReligionName) VALUES (%s)", (rel,))
            religion_ids.append(cur.lastrowid)

        # OccupationMaster
        occupations = ['Farmer', 'Government Employee', 'Private Employee', 'Business Owner', 'Student', 'Unemployed', 'Homemaker', 'Other']
        occupation_ids = []
        for occ in occupations:
            await cur.execute("INSERT INTO OccupationMaster (OccupationName) VALUES (%s)", (occ,))
            occupation_ids.append(cur.lastrowid)

        return {
            "district_ids": district_ids,
            "unit_ids": unit_ids,
            "court_ids": court_ids,
            "rank_ids": rank_ids,
            "designation_ids": designation_ids,
            "subhead_ids": subhead_ids,
            "category_ids": category_ids,
            "gravity_ids": gravity_ids,
            "status_ids": status_ids,
            "caste_ids": caste_ids,
            "religion_ids": religion_ids,
            "occupation_ids": occupation_ids,
            "head_ids": head_ids
        }

async def seed_employees(conn, lookups):
    officers_data = [
        {"name": "Manjunath Patil", "rank": "Inspector", "badge": "KSP-2010-0101", "role": "supervisor", "desg": "SHO"},
        {"name": "Venkatesh Gowda", "rank": "PI", "badge": "KSP-2012-0202", "role": "supervisor", "desg": "Circle Inspector"},
        {"name": "Ramesh Naik", "rank": "SI", "badge": "KSP-2014-0303", "role": "investigator", "desg": "Investigating Officer"},
        {"name": "Sandeep Hegde", "rank": "SI", "badge": "KSP-2015-0404", "role": "investigator", "desg": "Investigating Officer"},
        {"name": "Harish Kumar", "rank": "ASI", "badge": "KSP-2016-0505", "role": "investigator", "desg": "Investigating Officer"},
        {"name": "Vijay Raghavendra", "rank": "ASI", "badge": "KSP-2017-0606", "role": "investigator", "desg": "Investigating Officer"},
        {"name": "Lokesh Murthy", "rank": "Head Constable", "badge": "KSP-2018-0707", "role": "investigator", "desg": "Beat Officer"},
        {"name": "Shivakumar Swamy", "rank": "Head Constable", "badge": "KSP-2019-0808", "role": "investigator", "desg": "Beat Officer"},
        {"name": "Srinivas Raju", "rank": "Constable", "badge": "KSP-2020-0909", "role": "analyst", "desg": "Beat Officer"},
        {"name": "Naveen Raj", "rank": "Constable", "badge": "KSP-2021-1010", "role": "investigator", "desg": "Beat Officer"}
    ]

    employee_ids = []
    async with conn.cursor() as cur:
        for idx, off in enumerate(officers_data):
            dist_id = lookups["district_ids"][idx % 5]
            unit_id = lookups["unit_ids"][idx % 5]
            rank_id = lookups["rank_ids"][off["rank"]]
            desg_id = lookups["designation_ids"][off["desg"]]
            
            dob = date(1975, 1, 1) + timedelta(days=random.randint(0, 7000))
            gender_id = 1
            blood_group_id = random.randint(1, 8)
            app_date = date(2010, 1, 1) + timedelta(days=random.randint(0, 4000))
            
            sql = """
            INSERT INTO Employee (DistrictID, UnitID, RankID, DesignationID, KGID, FirstName, 
                                  EmployeeDOB, GenderID, BloodGroupID, PhysicallyChallenged, 
                                  AppointmentDate, role, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (
                dist_id, unit_id, rank_id, desg_id, off["badge"], off["name"],
                dob, gender_id, blood_group_id, 0, app_date, off["role"], 1
            ))
            emp_id = cur.lastrowid
            employee_ids.append({
                "id": emp_id,
                "district_id": dist_id,
                "unit_id": unit_id
            })
    return employee_ids

async def seed_cases(conn, lookups, employee_ids):
    cases_to_generate = []
    
    # Mahesh Gowda: 8 cases (4 theft, 2 assault, 1 robbery, 1 vehicle_theft)
    for _ in range(4):
        cases_to_generate.append({"case_type": "theft", "assigned_accused": "mahesh"})
    for _ in range(2):
        cases_to_generate.append({"case_type": "assault", "assigned_accused": "mahesh"})
    cases_to_generate.append({"case_type": "robbery", "assigned_accused": "mahesh"})
    cases_to_generate.append({"case_type": "vehicle_theft", "assigned_accused": "mahesh"})

    # Ravi Kumar: 5 cases (5 theft)
    for _ in range(5):
        cases_to_generate.append({"case_type": "theft", "assigned_accused": "ravi"})

    # Suresh Naik: 4 cases (4 fraud)
    for _ in range(4):
        cases_to_generate.append({"case_type": "fraud", "assigned_accused": "suresh"})

    # Deepak Rao: 3 cases (3 cybercrime)
    for _ in range(3):
        cases_to_generate.append({"case_type": "cybercrime", "assigned_accused": "deepak"})

    remaining_counts = {
        "theft": 41,
        "assault": 33,
        "vehicle_theft": 29,
        "fraud": 21,
        "cybercrime": 17,
        "missing_person": 15,
        "drug_offense": 15,
        "robbery": 9,
        "murder": 5,
        "domestic_violence": 10,
        "other": 5
    }

    for c_type, count in remaining_counts.items():
        for _ in range(count):
            cases_to_generate.append({"case_type": c_type, "assigned_accused": None})

    random.seed(42)
    random.shuffle(cases_to_generate)

    inserted_cases = []
    start_date_val = date(2022, 1, 1)
    end_date_val = date(2025, 6, 30)
    seq_counter = {}

    async with conn.cursor() as cur:
        for idx, case_data in enumerate(cases_to_generate):
            c_type = case_data["case_type"]
            assigned = case_data["assigned_accused"]
            
            emp = random.choice(employee_ids)
            emp_id = emp["id"]
            unit_id = emp["unit_id"]
            district_id = emp["district_id"]
            court_id = district_id
            
            reg_date = random_date(start_date_val, end_date_val)
            year = reg_date.year
            
            inc_from_time = random_time()
            inc_from = datetime.combine(reg_date - timedelta(days=random.randint(0, 3)), datetime.strptime(inc_from_time, "%H:%M:%S").time())
            inc_to = inc_from + timedelta(hours=random.randint(1, 4)) if random.random() < 0.5 else None
            info_received = datetime.combine(reg_date, datetime.strptime(random_time(), "%H:%M:%S").time())
            
            category_id = random.choices(lookups["category_ids"], weights=[0.90, 0.05, 0.03, 0.02])[0]
            seq_key = (district_id, unit_id, year)
            seq_counter[seq_key] = seq_counter.get(seq_key, 0) + 1
            
            crime_no = f"{category_id}{district_id:04d}{unit_id:04d}{year:04d}{seq_counter[seq_key]:05d}"
            case_no = crime_no[-9:]
            
            major_id = None
            minor_id = None
            if c_type in ['theft', 'robbery', 'vehicle_theft', 'fraud']:
                major_id = lookups["head_ids"][0]
                if c_type == 'theft':
                    minor_id = lookups["subhead_ids"]["Theft"]
                elif c_type == 'robbery':
                    minor_id = lookups["subhead_ids"]["Robbery"]
                elif c_type == 'vehicle_theft':
                    minor_id = lookups["subhead_ids"]["Vehicle Theft"]
                elif c_type == 'fraud':
                    minor_id = lookups["subhead_ids"]["Fraud"]
            elif c_type in ['assault', 'murder', 'domestic_violence', 'missing_person']:
                major_id = lookups["head_ids"][1]
                if c_type == 'assault':
                    minor_id = lookups["subhead_ids"]["Assault"]
                elif c_type == 'murder':
                    minor_id = lookups["subhead_ids"]["Murder"]
                elif c_type == 'domestic_violence':
                    minor_id = lookups["subhead_ids"]["Domestic Violence"]
                elif c_type == 'missing_person':
                    minor_id = lookups["subhead_ids"]["Missing Person"]
            elif c_type == 'cybercrime':
                major_id = lookups["head_ids"][2]
                sub_key = random.choice(["Phishing", "Online Harassment", "Identity Theft", "Hacking"])
                minor_id = lookups["subhead_ids"][sub_key]
            else:
                major_id = lookups["head_ids"][3]
                minor_id = lookups["subhead_ids"]["Drug Offense"]
            
            status_roll = random.random()
            if status_roll < 0.60:
                status_id = lookups["status_ids"]["Open"]
            elif status_roll < 0.85:
                status_id = lookups["status_ids"]["Under Investigation"]
            elif status_roll < 0.95:
                status_id = lookups["status_ids"]["Closed"]
            else:
                status_id = lookups["status_ids"]["Charge Sheeted"]
                
            if c_type in ['murder', 'robbery', 'domestic_violence']:
                gravity_id = lookups["gravity_ids"][0]
            else:
                gravity_id = lookups["gravity_ids"][1]
                
            loc = random.choice(LOCATIONS)
            lat = round(float(loc['lat']) + random.uniform(-0.005, 0.005), 8)
            lng = round(float(loc['lng']) + random.uniform(-0.005, 0.005), 8)
            
            desc = f"Reported case of {c_type} at {loc['name']}. Under investigation."
            if c_type == 'theft':
                desc = f"Complaint filed regarding theft of valuable personal assets from residential premises in {loc['name']}."
            elif c_type == 'assault':
                desc = f"Incident of physical assault reported following a verbal dispute between neighbors in {loc['name']}."
            elif c_type == 'vehicle_theft':
                desc = f"Theft of two-wheeler parked in front of owner's residence in {loc['name']}."
            elif c_type == 'fraud':
                desc = f"Victim was defrauded of money by suspects claiming to be bank officers, incident occurred in {loc['name']}."
            elif c_type == 'cybercrime':
                desc = f"Online phishing attempt resulting in unauthorized transactions on victim's credit card in {loc['name']}."
            elif c_type == 'missing_person':
                desc = f"Report filed regarding missing individual who was last seen walking near {loc['name']} bus stop."
            elif c_type == 'drug_offense':
                desc = f"Seizure of contraband substances and arrest of suspect in possession near local park in {loc['name']}."
            elif c_type == 'robbery':
                desc = f"Robbery at gun/knife point in a commercial area of {loc['name']}. Suspect fled scene."
            elif c_type == 'murder':
                desc = f"Homicide case registered following discovery of deceased person in an abandoned site in {loc['name']}."
            elif c_type == 'domestic_violence':
                desc = f"Domestic dispute and assault report registered by complainant in {loc['name']}."
                
            sql = """
            INSERT INTO CaseMaster (CrimeNo, CaseNo, CrimeRegisteredDate, PolicePersonID, PoliceStationID, 
                                    CaseCategoryID, GravityOffenceID, CrimeMajorHeadID, CrimeMinorHeadID, 
                                    CaseStatusID, CourtID, IncidentFromDate, IncidentToDate, InfoReceivedPSDate, 
                                    latitude, longitude, BriefFacts)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (
                crime_no, case_no, reg_date, emp_id, unit_id,
                category_id, gravity_id, major_id, minor_id,
                status_id, court_id, inc_from, inc_to, info_received,
                lat, lng, desc
            ))
            case_master_id = cur.lastrowid
            inserted_cases.append({
                "CaseMasterID": case_master_id,
                "case_type": c_type,
                "assigned_accused": assigned,
                "DistrictID": district_id,
                "PoliceStationID": unit_id,
                "CourtID": court_id,
                "PolicePersonID": emp_id,
                "CrimeRegisteredDate": reg_date,
                "location_name": loc["name"]
            })
            
    return inserted_cases

async def seed_complainants(conn, lookups, cases):
    async with conn.cursor() as cur:
        for case in cases:
            gender_id = random.choices([1, 2], weights=[0.60, 0.40])[0]
            if gender_id == 1:
                first = random.choice(MOCK_NAMES_MALE)
            else:
                first = random.choice(MOCK_NAMES_FEMALE)
            name = f"{first} {random.choice(MOCK_SURNAMES)}"
            age = random.randint(18, 75)
            caste_id = random.choice(lookups["caste_ids"])
            religion_id = random.choice(lookups["religion_ids"])
            occupation_id = random.choice(lookups["occupation_ids"])
            
            sql = """
            INSERT INTO ComplainantDetails (CaseMasterID, ComplainantName, AgeYear, OccupationID, 
                                            ReligionID, CasteID, GenderID)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (
                case["CaseMasterID"], name, age, occupation_id,
                religion_id, caste_id, gender_id
            ))

async def seed_victims(conn, lookups, cases):
    police_victim_indices = set(random.sample(range(len(cases)), 5))
    
    async with conn.cursor() as cur:
        for idx, case in enumerate(cases):
            gender_id = random.choices([1, 2], weights=[0.50, 0.50])[0]
            if gender_id == 1:
                first = random.choice(MOCK_NAMES_MALE)
            else:
                first = random.choice(MOCK_NAMES_FEMALE)
            name = f"{first} {random.choice(MOCK_SURNAMES)}"
            age = random.randint(1, 80)
            is_police = 1 if idx in police_victim_indices else 0
            
            sql = """
            INSERT INTO Victim (CaseMasterID, VictimName, AgeYear, GenderID, VictimPolice)
            VALUES (%s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (
                case["CaseMasterID"], name, age, gender_id, is_police
            ))

async def seed_accused(conn, lookups, cases):
    accused_records = []
    
    mahesh_cases = [c for c in cases if c["assigned_accused"] == "mahesh"]
    ravi_cases = [c for c in cases if c["assigned_accused"] == "ravi"]
    suresh_cases = [c for c in cases if c["assigned_accused"] == "suresh"]
    deepak_cases = [c for c in cases if c["assigned_accused"] == "deepak"]
    
    missing_cases = [c for c in cases if c["case_type"] == "missing_person"]
    other_cases = [c for c in cases if c["assigned_accused"] is None and c["case_type"] != "missing_person"]
    
    async with conn.cursor() as cur:
        # Mahesh Gowda: 8 cases
        for c in mahesh_cases:
            name = "Mahesh Gowda (alias Bullet Mahesh)"
            age = 34
            gender_id = 1
            person_id = "A1"
            
            sql = """
            INSERT INTO Accused (CaseMasterID, AccusedName, AgeYear, GenderID, PersonID)
            VALUES (%s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (c["CaseMasterID"], name, age, gender_id, person_id))
            accused_records.append({
                "AccusedMasterID": cur.lastrowid,
                "CaseMasterID": c["CaseMasterID"],
                "AccusedName": name
            })
            
        # Ravi Kumar: 5 cases
        for c in ravi_cases:
            name = "Ravi Kumar"
            age = 28
            gender_id = 1
            person_id = "A1"
            
            sql = """
            INSERT INTO Accused (CaseMasterID, AccusedName, AgeYear, GenderID, PersonID)
            VALUES (%s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (c["CaseMasterID"], name, age, gender_id, person_id))
            accused_records.append({
                "AccusedMasterID": cur.lastrowid,
                "CaseMasterID": c["CaseMasterID"],
                "AccusedName": name
            })

        # Suresh Naik: 4 cases
        for c in suresh_cases:
            name = "Suresh Naik"
            age = 45
            gender_id = 1
            person_id = "A1"
            
            sql = """
            INSERT INTO Accused (CaseMasterID, AccusedName, AgeYear, GenderID, PersonID)
            VALUES (%s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (c["CaseMasterID"], name, age, gender_id, person_id))
            accused_records.append({
                "AccusedMasterID": cur.lastrowid,
                "CaseMasterID": c["CaseMasterID"],
                "AccusedName": name
            })

        # Deepak Rao: 3 cases
        for c in deepak_cases:
            name = "Deepak Rao"
            age = 31
            gender_id = 1
            person_id = "A1"
            
            sql = """
            INSERT INTO Accused (CaseMasterID, AccusedName, AgeYear, GenderID, PersonID)
            VALUES (%s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (c["CaseMasterID"], name, age, gender_id, person_id))
            accused_records.append({
                "AccusedMasterID": cur.lastrowid,
                "CaseMasterID": c["CaseMasterID"],
                "AccusedName": name
            })

        # Unknown Suspect in 5 missing person cases
        for c in missing_cases[:5]:
            name = "Unknown Suspect"
            age = None
            gender_id = 3
            person_id = "A1"
            
            sql = """
            INSERT INTO Accused (CaseMasterID, AccusedName, AgeYear, GenderID, PersonID)
            VALUES (%s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (c["CaseMasterID"], name, age, gender_id, person_id))
            accused_records.append({
                "AccusedMasterID": cur.lastrowid,
                "CaseMasterID": c["CaseMasterID"],
                "AccusedName": name
            })

        # Partition remaining 185 cases
        three_acc_cases = other_cases[:10]
        two_acc_cases = other_cases[10:40]
        one_acc_cases = other_cases[40:]
        
        def get_random_accused_info():
            while True:
                gender = random.choices([1, 2, 3], weights=[0.85, 0.10, 0.05])[0]
                if gender == 1:
                    first = random.choice(MOCK_NAMES_MALE)
                elif gender == 2:
                    first = random.choice(MOCK_NAMES_FEMALE)
                else:
                    first = "Suspect"
                last = random.choice(MOCK_SURNAMES) if first != "Suspect" else ""
                name = f"{first} {last}".strip()
                if name not in ["Mahesh Gowda", "Ravi Kumar", "Suresh Naik", "Deepak Rao", "Mahesh Gowda (alias Bullet Mahesh)"]:
                    break
            age = random.randint(18, 65) if first != "Suspect" else None
            return name, age, gender

        for c in three_acc_cases:
            for p_idx in range(3):
                name, age, gender = get_random_accused_info()
                person_id = f"A{p_idx + 1}"
                sql = """
                INSERT INTO Accused (CaseMasterID, AccusedName, AgeYear, GenderID, PersonID)
                VALUES (%s, %s, %s, %s, %s)
                """
                await cur.execute(sql, (c["CaseMasterID"], name, age, gender, person_id))
                accused_records.append({
                    "AccusedMasterID": cur.lastrowid,
                    "CaseMasterID": c["CaseMasterID"],
                    "AccusedName": name
                })

        for c in two_acc_cases:
            for p_idx in range(2):
                name, age, gender = get_random_accused_info()
                person_id = f"A{p_idx + 1}"
                sql = """
                INSERT INTO Accused (CaseMasterID, AccusedName, AgeYear, GenderID, PersonID)
                VALUES (%s, %s, %s, %s, %s)
                """
                await cur.execute(sql, (c["CaseMasterID"], name, age, gender, person_id))
                accused_records.append({
                    "AccusedMasterID": cur.lastrowid,
                    "CaseMasterID": c["CaseMasterID"],
                    "AccusedName": name
                })

        for c in one_acc_cases:
            name, age, gender = get_random_accused_info()
            person_id = "A1"
            sql = """
                INSERT INTO Accused (CaseMasterID, AccusedName, AgeYear, GenderID, PersonID)
                VALUES (%s, %s, %s, %s, %s)
                """
            await cur.execute(sql, (c["CaseMasterID"], name, age, gender, person_id))
            accused_records.append({
                "AccusedMasterID": cur.lastrowid,
                "CaseMasterID": c["CaseMasterID"],
                "AccusedName": name
            })

    return accused_records

async def seed_act_sections(conn, cases):
    async with conn.cursor() as cur:
        for case in cases:
            c_type = case["case_type"]
            c_id = case["CaseMasterID"]
            sections_to_add = []
            
            if c_type == "theft":
                sections_to_add.append(("IPC", "379"))
                if random.random() < 0.15:
                    sections_to_add.append(("IPC", "323"))
            elif c_type == "murder":
                sections_to_add.append(("IPC", "302"))
                if random.random() < 0.25:
                    sections_to_add.append(("IPC", "323"))
            elif c_type == "robbery":
                sections_to_add.append(("IPC", "392"))
                if random.random() < 0.30:
                    sections_to_add.append(("IPC", "323"))
            elif c_type == "assault":
                sections_to_add.append(("IPC", "323"))
            elif c_type == "domestic_violence":
                sections_to_add.append(("IPC", "498A"))
                if random.random() < 0.20:
                    sections_to_add.append(("IPC", "323"))
            elif c_type == "drug_offense":
                sections_to_add.append(("NDPS", "20"))
                if random.random() < 0.20:
                    sections_to_add.append(("NDPS", "22"))
            elif c_type == "cybercrime":
                sec = random.choice(["66C", "66D"])
                sections_to_add.append(("IT Act", sec))
            else:
                if c_type != "missing_person":
                    sections_to_add.append(("IPC", "379"))
            
            for idx, (act_id, sec_id) in enumerate(sections_to_add):
                sql = """
                INSERT INTO ActSectionAssociation (CaseMasterID, ActID, SectionID, ActOrderID, SectionOrderID)
                VALUES (%s, %s, %s, %s, %s)
                """
                await cur.execute(sql, (c_id, act_id, sec_id, 1, idx + 1))

async def seed_arrest_surrender(conn, cases, accused_records):
    shuffled_accused = list(accused_records)
    random.shuffle(shuffled_accused)
    
    num_to_arrest = int(len(shuffled_accused) * 0.60)
    accused_to_arrest = shuffled_accused[:num_to_arrest]
    case_lookup = {c["CaseMasterID"]: c for c in cases}
    
    async with conn.cursor() as cur:
        for acc in accused_to_arrest:
            case = case_lookup[acc["CaseMasterID"]]
            arrest_date = case["CrimeRegisteredDate"] + timedelta(days=random.randint(1, 15))
            type_id = random.choices([1, 2], weights=[0.85, 0.15])[0]
            
            sql = """
            INSERT INTO ArrestSurrender (CaseMasterID, ArrestSurrenderTypeID, ArrestSurrenderDate, 
                                         ArrestSurrenderStateId, ArrestSurrenderDistrictId, PoliceStationID, 
                                         IOID, CourtID, AccusedMasterID, IsAccused, IsComplainantAccused)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (
                case["CaseMasterID"], type_id, arrest_date,
                1, case["DistrictID"], case["PoliceStationID"],
                case["PolicePersonID"], case["CourtID"], acc["AccusedMasterID"],
                1, 0
            ))

async def main():
    pool = await create_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM CaseMaster")
                row = await cur.fetchone()
                if row[0] > 0:
                    print("DB already seeded. Skipping seeder execution.")
                    return
            
            print("Seeding lookups...")
            lookups = await seed_lookups(conn)
            print("Seeding lookups... done")
            
            print("Seeding employees...")
            employee_ids = await seed_employees(conn, lookups)
            print(f"Seeding employees... done ({len(employee_ids)} rows)")
            
            print("Seeding CaseMaster...")
            cases = await seed_cases(conn, lookups, employee_ids)
            print(f"Seeding CaseMaster... done ({len(cases)} rows)")
            
            print("Seeding ComplainantDetails...")
            await seed_complainants(conn, lookups, cases)
            print("Seeding ComplainantDetails... done")
            
            print("Seeding Victim...")
            await seed_victims(conn, lookups, cases)
            print("Seeding Victim... done")
            
            print("Seeding Accused...")
            accused_records = await seed_accused(conn, lookups, cases)
            print(f"Seeding Accused... done ({len(accused_records)} rows)")
            
            print("Seeding ActSectionAssociation...")
            await seed_act_sections(conn, cases)
            print("Seeding ActSectionAssociation... done")
            
            print("Seeding ArrestSurrender...")
            await seed_arrest_surrender(conn, cases, accused_records)
            print("Seeding ArrestSurrender... done")
            
            print("Seed complete.")
    finally:
        await close_pool()

if __name__ == "__main__":
    asyncio.run(main())
