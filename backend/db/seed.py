import sys
import os
# Append backend root to sys.path so we can import from config
backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.append(backend_path)

import asyncio
import random
import json
import aiomysql
from datetime import datetime, date, timedelta
from db.connection import create_pool, close_pool, get_pool

# Set random seed for deterministic synthetic data generation
random.seed(42)

# Bengaluru Area locations with representative lat/lng
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

OFFICERS = [
    {"name": "Manjunath Patil", "rank": "Inspector", "badge": "KSP-2010-0101"},
    {"name": "Venkatesh Gowda", "rank": "PI", "badge": "KSP-2012-0202"},
    {"name": "Ramesh Naik", "rank": "SI", "badge": "KSP-2014-0303"},
    {"name": "Sandeep Hegde", "rank": "SI", "badge": "KSP-2015-0404"},
    {"name": "Harish Kumar", "rank": "ASI", "badge": "KSP-2016-0505"},
    {"name": "Vijay Raghavendra", "rank": "ASI", "badge": "KSP-2017-0606"},
    {"name": "Lokesh Murthy", "rank": "Head Constable", "badge": "KSP-2018-0707"},
    {"name": "Shivakumar Swamy", "rank": "Head Constable", "badge": "KSP-2019-0808"},
    {"name": "Srinivas Raju", "rank": "Constable", "badge": "KSP-2020-0909"},
    {"name": "Naveen Raj", "rank": "Constable", "badge": "KSP-2021-1010"}
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

async def seed_officers(conn) -> list[int]:
    """Insert 10 officers."""
    officer_ids = []
    async with conn.cursor() as cur:
        for off in OFFICERS:
            phone = f"9880{random.randint(100000, 999999)}"
            email = f"{off['name'].lower().replace(' ', '.')}@ksp.gov.in"
            date_joined = random_date(date(2010, 1, 1), date(2022, 1, 1))
            
            sql = """
            INSERT INTO officers (badge_number, full_name, `rank`, department, phone, email, date_joined, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (
                off['badge'], off['name'], off['rank'], "Crime Branch", phone, email, date_joined, True
            ))
            officer_ids.append(cur.lastrowid)
    return officer_ids

async def seed_fir_master(conn, officer_ids: list[int]) -> tuple[list[dict], dict]:
    """Insert 220 FIRs and return mappings of inserted records."""
    fir_records = []
    fir_ids_by_type = {
        'theft': [], 'robbery': [], 'assault': [], 'murder': [], 'fraud': [],
        'cybercrime': [], 'missing_person': [], 'vehicle_theft': [],
        'drug_offense': [], 'domestic_violence': [], 'other': []
    }
    
    # Target counts per case_type
    case_type_counts = {
        'theft': 50,
        'assault': 35,
        'vehicle_theft': 30,
        'fraud': 25,
        'cybercrime': 20,
        'missing_person': 15,
        'drug_offense': 15,
        'robbery': 10,
        'murder': 5,
        'domestic_violence': 10,
        'other': 5
    }
    
    start_date = date(2022, 1, 1)
    end_date = date(2025, 6, 30)
    station_code = "STN-KSP-BLR-01"
    
    # We will generate sequence numbers per year-location to format FIR numbers
    seq_counter = {}
    
    async with conn.cursor() as cur:
        for case_type, count in case_type_counts.items():
            for _ in range(count):
                loc = random.choice(LOCATIONS)
                dt_filed = random_date(start_date, end_date)
                tm_filed = random_time()
                year = dt_filed.year
                
                # Format FIR number
                seq_key = (year, loc['prefix'])
                seq_counter[seq_key] = seq_counter.get(seq_key, 0) + 1
                fir_number = f"FIR/{year}/{loc['prefix']}/{seq_counter[seq_key]:04d}"
                
                # incident date-time slightly before file date-time
                inc_date = dt_filed - timedelta(days=random.randint(0, 3))
                inc_time = random_time()
                
                # Lat/lng slightly perturbed from location center
                lat = float(loc['lat']) + random.uniform(-0.005, 0.005)
                lng = float(loc['lng']) + random.uniform(-0.005, 0.005)
                
                # Descriptions
                desc = f"Reported case of {case_type} at {loc['name']}. Under investigation."
                if case_type == 'theft':
                    desc = f"Complaint filed regarding theft of valuable personal assets from residential premises in {loc['name']}."
                elif case_type == 'assault':
                    desc = f"Incident of physical assault reported following a verbal dispute between neighbors in {loc['name']}."
                elif case_type == 'vehicle_theft':
                    desc = f"Theft of two-wheeler parked in front of owner's residence in {loc['name']}."
                elif case_type == 'fraud':
                    desc = f"Victim was defrauded of money by suspects claiming to be bank officers, incident occurred in {loc['name']}."
                elif case_type == 'cybercrime':
                    desc = f"Online phishing attempt resulting in unauthorized transactions on victim's credit card in {loc['name']}."
                elif case_type == 'missing_person':
                    desc = f"Report filed regarding missing individual who was last seen walking near {loc['name']} bus stop."
                elif case_type == 'drug_offense':
                    desc = f"Seizure of contraband substances and arrest of suspect in possession near local park in {loc['name']}."
                elif case_type == 'robbery':
                    desc = f"Robbery at gun/knife point in a commercial area of {loc['name']}. Suspect fled scene."
                elif case_type == 'murder':
                    desc = f"Homicide case registered following discovery of deceased person in an abandoned site in {loc['name']}."
                elif case_type == 'domestic_violence':
                    desc = f"Domestic dispute and assault report registered by complainant in {loc['name']}."
                
                # Status distribution: 60% open, 25% under_investigation, 10% closed, 5% chargesheeted
                status_roll = random.random()
                if status_roll < 0.60:
                    status = 'open'
                elif status_roll < 0.85:
                    status = 'under_investigation'
                elif status_roll < 0.95:
                    status = 'closed'
                else:
                    status = 'chargesheeted'
                    
                officer_id = random.choice(officer_ids)
                
                sql = """
                INSERT INTO fir_master (fir_number, station_code, date_filed, time_filed, case_type, 
                                        incident_date, incident_time, incident_location, incident_lat, 
                                        incident_lng, description, status, investigating_officer_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                await cur.execute(sql, (
                    fir_number, station_code, dt_filed, tm_filed, case_type,
                    inc_date, inc_time, f"{loc['name']}, Bengaluru", lat, lng,
                    desc, status, officer_id
                ))
                
                fir_id = cur.lastrowid
                record = {
                    "fir_id": fir_id,
                    "fir_number": fir_number,
                    "case_type": case_type,
                    "incident_location": loc['name'],
                    "date_filed": dt_filed
                }
                fir_records.append(record)
                fir_ids_by_type[case_type].append(fir_id)
                
    return fir_records, fir_ids_by_type

async def seed_accused(conn, fir_records: list[dict], fir_ids_by_type: dict):
    """Insert accused persons, ensuring repeat offender patterns are preserved."""
    
    # Extract FIR IDs for specific categories
    theft_firs = fir_ids_by_type['theft']
    assault_firs = fir_ids_by_type['assault']
    robbery_firs = fir_ids_by_type['robbery']
    vehicle_theft_firs = fir_ids_by_type['vehicle_theft']
    fraud_firs = fir_ids_by_type['fraud']
    cybercrime_firs = fir_ids_by_type['cybercrime']
    
    # Store explicit repeat offender allocations to ensure we meet count criteria
    # Mahesh Gowda: 8 FIRs (4 theft, 2 assault, 1 robbery, 1 vehicle_theft)
    mahesh_firs = [
        theft_firs.pop(0), theft_firs.pop(0), theft_firs.pop(0), theft_firs.pop(0),
        assault_firs.pop(0), assault_firs.pop(0),
        robbery_firs.pop(0),
        vehicle_theft_firs.pop(0)
    ]
    
    # Ravi Kumar: 5 theft FIRs
    ravi_firs = [theft_firs.pop(0) for _ in range(5)]
    
    # Suresh Nayak: 4 fraud FIRs
    suresh_firs = [fraud_firs.pop(0) for _ in range(4)]
    
    # Pavan Reddy: 3 cybercrime FIRs
    pavan_firs = [cybercrime_firs.pop(0) for _ in range(3)]
    
    # Anand Shetty: 3 assault FIRs
    anand_firs = [assault_firs.pop(0) for _ in range(3)]
    
    repeat_offenders = [
        {
            "name": "Mahesh Gowda",
            "alias": "Bullet Mahesh",
            "age": 34,
            "gender": "male",
            "address": "No 42, 1st Cross, Koramangala, Bengaluru",
            "id_type": "Aadhaar",
            "id_number": "3421-9988-1002",
            "prior_fir_count": 8,
            "arrest_status": "at_large",
            "notes": "Known leader of regional theft and assault gang. Frequents Koramangala and HSR Layout.",
            "firs": mahesh_firs
        },
        {
            "name": "Ravi Kumar",
            "alias": "Ravi Thief",
            "age": 28,
            "gender": "male",
            "address": "Slum Area near Shivajinagar, Bengaluru",
            "id_type": "PAN",
            "id_number": "BVPPR4532L",
            "prior_fir_count": 5,
            "arrest_status": "arrested",
            "notes": "Habitual house thief. Specializes in breaking window grilles.",
            "firs": ravi_firs
        },
        {
            "name": "Suresh Nayak",
            "alias": "None",
            "age": 45,
            "gender": "male",
            "address": "Flat 302, Green Glen Layout, Bellandur, Bengaluru",
            "id_type": "Aadhaar",
            "id_number": "9088-7711-2233",
            "prior_fir_count": 4,
            "arrest_status": "at_large",
            "notes": "White-collar criminal involved in property sales fraud.",
            "firs": suresh_firs
        },
        {
            "name": "Pavan Reddy",
            "alias": "None",
            "age": 26,
            "gender": "male",
            "address": "PG Accommodation, Hebbal, Bengaluru",
            "id_type": "Aadhaar",
            "id_number": "5432-8877-1199",
            "prior_fir_count": 3,
            "arrest_status": "at_large",
            "notes": "Handles phishing page design and domain deployment.",
            "firs": pavan_firs
        },
        {
            "name": "Anand Shetty",
            "alias": "None",
            "age": 39,
            "gender": "male",
            "address": "Benson Town, Shivajinagar, Bengaluru",
            "id_type": "Aadhaar",
            "id_number": "1290-7856-3412",
            "prior_fir_count": 3,
            "arrest_status": "arrested",
            "notes": "Short-tempered, involved in multiple bar fights and street brawls.",
            "firs": anand_firs
        }
    ]
    
    # Track which FIRs are already allocated to repeat offenders
    allocated_firs = set(mahesh_firs + ravi_firs + suresh_firs + pavan_firs + anand_firs)
    
    # We need to assign accused to the remaining FIRs.
    # Total FIRs = 220. We will seed:
    # - 30 FIRs: 2 accused
    # - 10 FIRs: 3 accused
    # - The rest: 1 accused (except missing_person cases, where there's usually no accused, but we can seed 'unknown' or a suspect for some)
    # Let's collect all remaining non-missing FIR IDs.
    remaining_firs = [f["fir_id"] for f in fir_records if f["fir_id"] not in allocated_firs and f["case_type"] != "missing_person"]
    
    async with conn.cursor() as cur:
        # 1. Insert repeat offenders
        for rep in repeat_offenders:
            for f_id in rep["firs"]:
                sql = """
                INSERT INTO accused (fir_id, full_name, alias, age, gender, address, id_type, id_number, prior_fir_count, arrest_status, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                await cur.execute(sql, (
                    f_id, rep["name"], rep["alias"], rep["age"], rep["gender"],
                    rep["address"], rep["id_type"], rep["id_number"], rep["prior_fir_count"],
                    rep["arrest_status"], rep["notes"]
                ))
                
        # 2. Distribute remaining accused
        # Let's partition the remaining FIRs:
        # First 10 FIRs: 3 accused each
        # Next 30 FIRs: 2 accused each
        # Remaining FIRs: 1 accused each
        
        three_accused_firs = remaining_firs[:10]
        two_accused_firs = remaining_firs[10:40]
        one_accused_firs = remaining_firs[40:]
        
        # Helper to generate a random accused person
        def make_random_accused(f_id):
            gender = random.choices(["male", "female", "unknown"], weights=[0.85, 0.10, 0.05])[0]
            if gender == "male":
                first = random.choice(MOCK_NAMES_MALE)
            elif gender == "female":
                first = random.choice(MOCK_NAMES_FEMALE)
            else:
                first = "Suspect"
            last = random.choice(MOCK_SURNAMES) if first != "Suspect" else ""
            name = f"{first} {last}".strip()
            
            alias = random.choice(["None", f"\"{first} Thief\"", "None", "None"])
            age = random.randint(18, 60)
            addr = f"No {random.randint(1, 100)}, Cross Road, Bengaluru"
            phone = f"9{random.randint(100000000, 999999999)}"
            id_type = random.choice(["Aadhaar", "PAN", "Voter ID", "None"])
            id_num = f"{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}" if id_type == "Aadhaar" else f"ID-{random.randint(10000, 99999)}"
            prior = random.choices([0, 1, 2], weights=[0.8, 0.15, 0.05])[0]
            arr_status = random.choices(["arrested", "at_large", "unknown"], weights=[0.4, 0.5, 0.1])[0]
            
            return (f_id, name, alias, age, gender, addr, phone, id_type, id_num, prior, arr_status)

        for f_id in three_accused_firs:
            for _ in range(3):
                data = make_random_accused(f_id)
                sql = """
                INSERT INTO accused (fir_id, full_name, alias, age, gender, address, phone, id_type, id_number, prior_fir_count, arrest_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                await cur.execute(sql, data)
                
        for f_id in two_accused_firs:
            for _ in range(2):
                data = make_random_accused(f_id)
                sql = """
                INSERT INTO accused (fir_id, full_name, alias, age, gender, address, phone, id_type, id_number, prior_fir_count, arrest_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                await cur.execute(sql, data)

        for f_id in one_accused_firs:
            data = make_random_accused(f_id)
            sql = """
            INSERT INTO accused (fir_id, full_name, alias, age, gender, address, phone, id_type, id_number, prior_fir_count, arrest_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, data)
            
        # Add suspects/unknowns to missing_person cases as notes or optional accused in 5 of them
        missing_person_firs = fir_ids_by_type['missing_person']
        for mp_f_id in missing_person_firs[:5]:
            sql = """
            INSERT INTO accused (fir_id, full_name, alias, age, gender, notes)
            VALUES (%s, 'Unknown Suspect', 'None', NULL, 'unknown', 'Suspicion of kidnapping or foul play.')
            """
            await cur.execute(sql, (mp_f_id,))

async def seed_victims(conn, fir_records: list[dict]):
    """Insert one victim per FIR."""
    async with conn.cursor() as cur:
        for rec in fir_records:
            f_id = rec["fir_id"]
            case_type = rec["case_type"]
            
            gender = random.choice(["male", "female"])
            if gender == "male":
                first = random.choice(MOCK_NAMES_MALE)
            else:
                first = random.choice(MOCK_NAMES_FEMALE)
            name = f"{first} {random.choice(MOCK_SURNAMES)}"
            
            age = random.randint(18, 70)
            addr = f"Resident of {rec['incident_location']}, Bengaluru"
            phone = f"9845{random.randint(100000, 999999)}"
            
            if case_type == "missing_person":
                inj = "Missing individual (complainant's relative)."
            elif case_type == "assault" or case_type == "domestic_violence":
                inj = random.choice(["Bruises on face and arms", "Laceration on right hand", "Minor head injury", "No visible external injury"])
            else:
                inj = "No physical injury reported."
                
            sql = """
            INSERT INTO victims (fir_id, full_name, age, gender, address, phone, injury_description)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (f_id, name, age, gender, addr, phone, inj))

async def seed_case_type_tables(conn, fir_ids_by_type: dict):
    """Populate details in specific child case tables."""
    async with conn.cursor() as cur:
        
        # 1. cases_theft
        theft_items = [
            '["gold necklace", "gold bangles"]',
            '["Dell Laptop", "Office Files"]',
            '["iPhone 14 Pro Max", "Leather Wallet"]',
            '["Cash INR 50,000"]',
            '["Bicycle", "Toolbox"]',
            '["Television", "Soundbar"]'
        ]
        for f_id in fir_ids_by_type['theft']:
            items = random.choice(theft_items)
            val = random.randint(500, 150000)
            recovered = random.random() < 0.20
            rec_dt = None
            rec_notes = None
            if recovered:
                rec_dt = date(2024, 1, 1) + timedelta(days=random.randint(1, 100))
                rec_notes = "Recovered from local pawn shop."
                
            sql = """
            INSERT INTO cases_theft (fir_id, stolen_items, estimated_value, recovered, recovery_date, recovery_notes)
            VALUES (%s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (f_id, items, val, recovered, rec_dt, rec_notes))

        # 2. cases_assault
        weapons = ["iron rod", "knife", "bare hands", "stone", "bottle"]
        severities = ["minor", "moderate", "severe", "fatal"]
        severities_weights = [0.60, 0.25, 0.12, 0.03]
        for f_id in fir_ids_by_type['assault']:
            w = random.choice(weapons)
            sev = random.choices(severities, weights=severities_weights)[0]
            mot = random.choice(["Property dispute", "Personal enmity", "Drunk brawl", "Road rage"])
            w_count = random.randint(0, 4)
            
            sql = """
            INSERT INTO cases_assault (fir_id, weapon_used, injury_severity, motive, witnesses_count)
            VALUES (%s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (f_id, w, sev, mot, w_count))
            
        # 3. cases_vehicle_theft
        makes = {
            "two_wheeler": ["Honda", "Hero", "TVS", "Royal Enfield", "Yamaha"],
            "car": ["Maruti Suzuki", "Hyundai", "Tata Motors", "Mahindra", "Toyota"],
            "truck": ["Tata", "Ashok Leyland"],
            "auto": ["Bajaj", "Piaggio"],
            "other": ["Electric Scooter"]
        }
        for f_id in fir_ids_by_type['vehicle_theft']:
            v_type = random.choices(
                ["two_wheeler", "car", "auto", "truck", "other"],
                weights=[0.50, 0.35, 0.10, 0.03, 0.02]
            )[0]
            make = random.choice(makes[v_type])
            model = "Model-" + random.choice(["A", "B", "C", "Classic", "Deluxe"])
            reg = f"KA-{random.randint(1, 5):02d}-{random.choice(['M', 'N', 'P', 'R'])}{random.choice(['A', 'B', 'C'])}-{random.randint(1000, 9999)}"
            color = random.choice(["Black", "White", "Silver", "Red", "Blue"])
            
            recovered = random.random() < 0.25
            rec_dt = None
            rec_loc = None
            if recovered:
                recovered = True
                rec_dt = date(2024, 1, 1) + timedelta(days=random.randint(1, 100))
                rec_loc = random.choice(LOCATIONS)["name"] + ", Bengaluru"
                
            sql = """
            INSERT INTO cases_vehicle_theft (fir_id, vehicle_type, vehicle_make, vehicle_model, registration_no, color, recovered, recovery_date, recovery_location)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (f_id, v_type, make, model, reg, color, recovered, rec_dt, rec_loc))

        # 4. cases_fraud
        fraud_types = ["online", "banking", "property", "offline"]
        for f_id in fir_ids_by_type['fraud']:
            f_type = random.choices(fraud_types, weights=[0.40, 0.30, 0.20, 0.10])[0]
            amt = random.randint(5000, 2000000)
            recovered_amt = int(amt * random.choice([0.0, 0.0, 0.0, 0.1, 0.25, 0.5]))
            method = random.choice(["UPI fraudulent link", "Fake real estate documentation", "Phishing calls for OTP", "Duplicate check clearance"])
            accs = json.dumps([f"SBI-{random.randint(100000000, 999999999)}", f"HDFC-{random.randint(100000000, 999999999)}"])
            
            sql = """
            INSERT INTO cases_fraud (fir_id, fraud_type, amount_defrauded, amount_recovered, method_used, account_numbers)
            VALUES (%s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (f_id, f_type, amt, recovered_amt, method, accs))

        # 5. cases_cybercrime
        cyber_types = ["phishing", "online_harassment", "identity_theft", "hacking"]
        platforms = ["WhatsApp", "Instagram", "email", "Facebook", "unknown"]
        for f_id in fir_ids_by_type['cybercrime']:
            c_type = random.choices(cyber_types, weights=[0.40, 0.25, 0.20, 0.15])[0]
            plat = random.choice(platforms)
            loss = random.randint(1000, 500000) if c_type in ["phishing", "identity_theft", "hacking"] else 0
            devs = json.dumps({
                "source_ip": f"192.168.{random.randint(1, 254)}.{random.randint(1, 254)}",
                "device_id": f"DEV-{random.randint(100000, 999999)}",
                "urls": ["http://fake-banking-portal.net", "http://update-kyc-now.co"]
            })
            
            sql = """
            INSERT INTO cases_cybercrime (fir_id, cyber_type, platform, financial_loss, digital_evidence)
            VALUES (%s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (f_id, c_type, plat, loss, devs))

        # 6. cases_missing_person
        conditions = ["safe", "injured", "deceased", "unknown"]
        for f_id in fir_ids_by_type['missing_person']:
            since = date(2023, 1, 1) + timedelta(days=random.randint(1, 500))
            last_seen = random.choice(LOCATIONS)["name"] + " Bus Stop"
            phys_desc = "Height: 5'6\", Age: 25, Wearing blue shirt and jeans. Mole on right cheek."
            
            found = random.random() < 0.40
            f_dt = None
            f_loc = None
            f_cond = "unknown"
            if found:
                f_dt = since + timedelta(days=random.randint(1, 60))
                f_loc = random.choice(LOCATIONS)["name"] + ", Bengaluru"
                f_cond = random.choices(conditions, weights=[0.75, 0.15, 0.05, 0.05])[0]
                
            sql = """
            INSERT INTO cases_missing_person (fir_id, missing_since, last_seen_location, physical_description, found, found_date, found_location, found_condition)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (f_id, since, last_seen, phys_desc, found, f_dt, f_loc, f_cond))

        # 7. cases_drug_offense
        drugs = ["ganja", "cocaine", "heroin", "MDMA", "methamphetamine"]
        seized_text = ["500 grams", "2 kg", "100 tablets", "50 grams", "1.5 kg"]
        for f_id in fir_ids_by_type['drug_offense']:
            d_type = random.choice(drugs)
            qty = random.choice(seized_text)
            val = random.randint(10000, 500000)
            src = random.choice(LOCATIONS)["name"] + " High School Road"
            
            sql = """
            INSERT INTO cases_drug_offense (fir_id, drug_type, quantity_seized, estimated_street_value, source_location)
            VALUES (%s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (f_id, d_type, qty, val, src))

async def seed_case_relationships(conn):
    """Insert 35 relationship records that form network clusters."""
    async with conn.cursor(aiomysql.DictCursor) as cur:
        # We need the IDs of accused, which we can fetch by name or index
        # Let's get the accused IDs
        await cur.execute("SELECT accused_id, full_name, fir_id FROM accused")
        accused_rows = await cur.fetchall()
        
        # Group accused by full name
        accused_by_name = {}
        for row in accused_rows:
            name = row["full_name"]
            accused_by_name.setdefault(name, []).append(row)
            
        mahesh_records = accused_by_name.get("Mahesh Gowda", [])
        ravi_records = accused_by_name.get("Ravi Kumar", [])
        suresh_records = accused_by_name.get("Suresh Nayak", [])
        pavan_records = accused_by_name.get("Pavan Reddy", [])
        
        # Let's also fetch a few other random accused to link them
        other_accused = [row for name, rows in accused_by_name.items() if name not in ["Mahesh Gowda", "Ravi Kumar", "Suresh Nayak", "Pavan Reddy"] for row in rows]
        random.shuffle(other_accused)

        relationship_count = 0

        # Cluster 1 — The Bullet Mahesh gang (8 entries):
        # Link Mahesh Gowda as co_accused with 3 other accused across his FIRs.
        # Link his 8 FIRs as related_case to each other.
        if len(mahesh_records) >= 8 and len(other_accused) >= 3:
            # Pick 3 other accused
            gang_members = other_accused[:3]
            # Link Mahesh's accused_id to these members in the same FIR
            for member in gang_members:
                sql = """
                INSERT INTO case_relationships (entity_a_type, entity_a_id, entity_b_type, entity_b_id, relationship_type, notes)
                VALUES ('accused', %s, 'accused', %s, 'co_accused', 'Active members of the Bullet Mahesh network.')
                """
                await cur.execute(sql, (mahesh_records[0]["accused_id"], member["accused_id"]))
                relationship_count += 1
                
            # Link Mahesh's 5 FIRs in pairs (related_case)
            for i in range(5):
                sql = """
                INSERT INTO case_relationships (entity_a_type, entity_a_id, entity_b_type, entity_b_id, relationship_type, notes)
                VALUES ('fir', %s, 'fir', %s, 'related_case', 'Cases associated with the Mahesh Gowda gang.')
                """
                await cur.execute(sql, (mahesh_records[i]["fir_id"], mahesh_records[i+1]["fir_id"]))
                relationship_count += 1

        # Cluster 2 — Ravi Thief network (5 entries):
        # Link Ravi Kumar's 5 FIRs as related_case.
        # Link him as co_accused with 1 other accused in 2 of his cases.
        if len(ravi_records) >= 5 and len(other_accused) >= 5:
            # Link Ravi's 5 FIRs sequentially
            for i in range(4):
                sql = """
                INSERT INTO case_relationships (entity_a_type, entity_a_id, entity_b_type, entity_b_id, relationship_type, notes)
                VALUES ('fir', %s, 'fir', %s, 'related_case', 'Series of break-ins linked to Ravi Thief.')
                """
                await cur.execute(sql, (ravi_records[i]["fir_id"], ravi_records[i+1]["fir_id"]))
                relationship_count += 1
                
            # Link him as co_accused with another accused
            sql = """
            INSERT INTO case_relationships (entity_a_type, entity_a_id, entity_b_type, entity_b_id, relationship_type, notes)
            VALUES ('accused', %s, 'accused', %s, 'co_accused', 'Accomplice in home robbery.')
            """
            await cur.execute(sql, (ravi_records[0]["accused_id"], other_accused[4]["accused_id"]))
            relationship_count += 1

        # Cluster 3 — Online fraud ring (6 entries):
        # Link Suresh Nayak and Pavan Reddy as co_accused.
        # Link their FIRs as same_modus_operandi.
        if suresh_records and pavan_records:
            # Link Suresh and Pavan
            sql = """
            INSERT INTO case_relationships (entity_a_type, entity_a_id, entity_b_type, entity_b_id, relationship_type, notes)
            VALUES ('accused', %s, 'accused', %s, 'co_accused', 'Suresh coordinates bank accounts; Pavan deploys phishing URLs.')
            """
            await cur.execute(sql, (suresh_records[0]["accused_id"], pavan_records[0]["accused_id"]))
            relationship_count += 1
            
            # Link 5 of their FIRs as same_modus_operandi
            limit = min(len(suresh_records), len(pavan_records))
            for i in range(limit):
                sql = """
                INSERT INTO case_relationships (entity_a_type, entity_a_id, entity_b_type, entity_b_id, relationship_type, notes)
                VALUES ('fir', %s, 'fir', %s, 'same_modus_operandi', 'Online banking scams using similar domain registration details.')
                """
                await cur.execute(sql, (suresh_records[i]["fir_id"], pavan_records[i]["fir_id"]))
                relationship_count += 1

        # Cluster 4 — Same location repeat (4 entries):
        # Pick 4 unrelated theft FIRs that all have incident_location = "Koramangala".
        # Link them as repeat_location.
        # Let's query Koramangala theft FIRs
        await cur.execute("SELECT fir_id FROM fir_master WHERE incident_location LIKE 'Koramangala%' AND case_type='theft' LIMIT 4")
        kor_thefts = await cur.fetchall()
        if len(kor_thefts) >= 4:
            for i in range(3):
                sql = """
                INSERT INTO case_relationships (entity_a_type, entity_a_id, entity_b_type, entity_b_id, relationship_type, notes)
                VALUES ('fir', %s, 'fir', %s, 'repeat_location', 'Multiple thefts reported in near vicinity in Koramangala.')
                """
                await cur.execute(sql, (kor_thefts[i]["fir_id"], kor_thefts[i+1]["fir_id"]))
                relationship_count += 1

        # Remaining: misc linked cases across different types
        while relationship_count < 35 and len(other_accused) >= 2:
            acc_a = other_accused.pop(0)
            acc_b = other_accused.pop(0)
            sql = """
            INSERT INTO case_relationships (entity_a_type, entity_a_id, entity_b_type, entity_b_id, relationship_type, notes)
            VALUES ('accused', %s, 'accused', %s, 'co_accused', 'Suspected gang association.')
            """
            await cur.execute(sql, (acc_a["accused_id"], acc_b["accused_id"]))
            relationship_count += 1

async def seed_evidence_media(conn, fir_records: list[dict]):
    """Insert 25 evidence_media records."""
    # Pick 25 random FIR IDs
    firs_to_seed = random.sample(fir_records, 25)
    
    media_types = ["image", "video", "audio"]
    descriptions = {
        "image": [
            "Crime scene photo showing point of entry",
            "CCTV image of vehicle suspect fled in",
            "Recovered stolen gold jewelry picture",
            "Assault victim injury photo (evidence record)"
        ],
        "video": [
            "CCTV footage from street camera at incident time",
            "Suspect dashcam recording from traffic signal",
            "Video recording of witness identifying suspect at station"
        ],
        "audio": [
            "Witness statement audio recording",
            "911 emergency call audio backup",
            "Suspect voice call record intercepts"
        ]
    }
    
    async with conn.cursor() as cur:
        for idx, rec in enumerate(firs_to_seed):
            f_id = rec["fir_id"]
            # Distribute: 15 image, 6 video, 4 audio
            if idx < 15:
                m_type = "image"
            elif idx < 21:
                m_type = "video"
            else:
                m_type = "audio"
                
            desc = random.choice(descriptions[m_type])
            f_name = f"evidence_{f_id}_{idx:02d}.mp4" if m_type == "video" else (f"evidence_{f_id}_{idx:02d}.mp3" if m_type == "audio" else f"evidence_{f_id}_{idx:02d}.jpg")
            folder_id = f"folder_placeholder_{random.randint(100, 999)}"
            file_id = f"file_placeholder_{random.randint(10000, 99999)}"
            
            sql = """
            INSERT INTO evidence_media (fir_id, media_type, file_name, stratus_folder_id, stratus_file_id, description)
            VALUES (%s, %s, %s, %s, %s, %s)
            """
            await cur.execute(sql, (f_id, m_type, f_name, folder_id, file_id, desc))

async def main():
    """Entry point. Checks if DB already has data (count fir_master rows)."""
    # Create the DB pool
    pool = await create_pool()
    
    try:
        async with pool.acquire() as conn:
            # Check row count
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) as count FROM fir_master")
                row = await cur.fetchone()
                if row[0] > 0:
                    print("DB already seeded. Skipping seeder execution.")
                    return
            
            print("Seeding officers...")
            officer_ids = await seed_officers(conn)
            print(f"Seeding officers... done ({len(officer_ids)} rows)")
            
            print("Seeding FIR master...")
            fir_records, fir_ids_by_type = await seed_fir_master(conn, officer_ids)
            print(f"Seeding FIR master... done ({len(fir_records)} rows)")
            
            print("Seeding accused...")
            await seed_accused(conn, fir_records, fir_ids_by_type)
            
            # Print total count of accused
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM accused")
                accused_count = (await cur.fetchone())[0]
            print(f"Seeding accused... done ({accused_count} rows)")
            
            print("Seeding victims...")
            await seed_victims(conn, fir_records)
            print("Seeding victims... done")
            
            print("Seeding case type tables...")
            await seed_case_type_tables(conn, fir_ids_by_type)
            print("Seeding case type tables... done")
            
            print("Seeding case relationships...")
            await seed_case_relationships(conn)
            
            # Print total count of relationships
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM case_relationships")
                rel_count = (await cur.fetchone())[0]
            print(f"Seeding case relationships... done ({rel_count} rows)")
            
            print("Seeding evidence media...")
            await seed_evidence_media(conn, fir_records)
            print("Seeding evidence media... done")
            
            print("Seed complete.")
            
    finally:
        await close_pool()

if __name__ == "__main__":
    # Standard check to allow running standalone or inside package
    import sys
    import os
    # Append backend root to sys.path so we can import from config
    backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_path not in sys.path:
        sys.path.append(backend_path)
    asyncio.run(main())
