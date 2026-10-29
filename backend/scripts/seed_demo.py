"""Seed the configured Firebase project with demo patent data.

Development helper only. It writes to the Firestore database that `.env`
points at, so it refuses to run when ENVIRONMENT=production.

    python scripts/seed_demo.py --dry-run   # show the plan, write nothing
    python scripts/seed_demo.py             # add demo records (idempotent)
    python scripts/seed_demo.py --reset     # delete the demo records, then reseed
    python scripts/seed_demo.py --reset-only

Every document written here carries ``demo_seed = "demo-seed-v1"`` (blobs are
tagged right after upload) and gets a ``demo-`` id, so ``--reset`` removes
exactly the seeded records and never touches real data. Records that already
exist are left untouched, which makes repeated runs safe.

The two accounts must exist already: sign in with Google once, then run this.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow `python scripts/seed_demo.py` from backend/ without installing the app.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.firebase import db, initialize_firebase
from app.services import blobs, documents
from app.services.drafting import SECTION_TYPES
from app.services.repository import create_doc, patch_doc, query_docs

SEED_TAG = "demo-seed-v1"
USER_EMAILS = (
    "priyangshumukherjee07@gmail.com",
    "mmanishablr@gmail.com",
)

# Collections that can contain seeded documents. Teams carry a `members`
# subcollection, which is deleted with its parent.
SEEDED_COLLECTIONS = (
    "patents",
    "questionnaires",
    "questionnaire_versions",
    "drafts",
    "applicants",
    "inventors",
    "documents",
    "document_versions",
    "document_jobs",
    "document_counters",
    "comments",
    "calendar_events",
    "notifications",
    "activity",
    "assignment_history",
    "blobs",
    "teams",
)

TEAMS = (
    {"key": "energy", "name": "Aero & Energy Labs"},
    {"key": "biomed", "name": "BioMed Devices"},
    {"key": "agri", "name": "AgriTech Collective"},
    {"key": "water", "name": "Water & Sanitation"},
    # Aura's own lab: only mmanishablr is a member, so this portfolio is
    # distinct from the shared teams above (a Super Admin still sees it all).
    {"key": "aura", "name": "Aura Health Labs", "members": ("mmanishablr@gmail.com",)},
)

TEAM_MEMBERS = ("priyangshumukherjee07@gmail.com", "mmanishablr@gmail.com")

PATENTS = (
    {
        "key": "solar-cooker",
        "title": "Adaptive Solar Cooker with Phase-Change Thermal Storage",
        "status": "Draft",
        "team": "energy",
        "owner": "priyangshumukherjee07@gmail.com",
        "agent": None,
        "questionnaire": "in_progress",
        "created_days_ago": 1,
        "details": {
            "invention_type": "Mechanical",
            "problem_statement": (
                "Concentrated solar cookers lose usable heat within an hour of "
                "sunset and cannot hold a stable cooking temperature on cloudy days."
            ),
            "proposed_solution": (
                "A parabolic concentrator couples to a segmented phase-change salt "
                "sleeve that stores heat at two melting points and releases it through "
                "a thermostatic damper."
            ),
            "novelty_description": (
                "The storage sleeve is split into concentric cells filled with salts of "
                "different melting points, so heat is released in stages instead of one "
                "falling temperature curve."
            ),
            "advantages": (
                "Cooks for three hours after sunset, needs no electricity, and keeps "
                "the chamber within a 20-degree band."
            ),
            "prior_art": (
                "Thermal-storage solar cookers use a single salt or oil bath, which "
                "releases heat over a wide and rapidly falling temperature range."
            ),
            "keywords": "solar cooking, phase change material, thermal storage, damper",
            "has_existing_drawings": True,
        },
    },
    {
        "key": "hydroponic",
        "title": "Modular Hydroponic Tower for Urban Farms",
        "status": "Draft",
        "team": "agri",
        "owner": "mmanishablr@gmail.com",
        "agent": None,
        "questionnaire": "in_progress",
        "created_days_ago": 2,
        "details": {
            "invention_type": "Mechanical",
            "problem_statement": (
                "Balcony hydroponic towers are sold as fixed-height columns, so a "
                "single unit cannot be adapted from herbs to fruiting crops."
            ),
            "proposed_solution": (
                "Stackable growth modules clip onto a shared riser, and each module "
                "carries its own drip ring and drain channel."
            ),
            "novelty_description": (
                "The riser uses a quarter-turn bayonet joint with an integral O-ring, "
                "so modules can be added or removed without draining the reservoir."
            ),
            "advantages": "Converts a 60 cm balcony rail into a 12-plant garden.",
        },
    },
    {
        "key": "ecg-patch",
        "title": "Wearable ECG Patch with Dry Graphene Electrodes",
        "status": "Submitted",
        "team": "biomed",
        "owner": "mmanishablr@gmail.com",
        "agent": None,
        "questionnaire": "completed",
        "created_days_ago": 4,
        "details": {
            "invention_type": "Electronics",
            "problem_statement": (
                "Ambulatory ECG patches rely on hydrogel electrodes that dry out "
                "within 48 hours and irritate sensitive skin."
            ),
            "proposed_solution": (
                "A flexible patch carries laser-scribed graphene electrodes and a "
                "low-noise analog front end that tolerates high skin impedance."
            ),
            "novelty_description": (
                "The electrode layer is laser-scribed directly onto the same polyimide "
                "sheet that carries the acquisition circuit, removing the gel interface."
            ),
            "technical_description": (
                "A 0.3 mm polyimide stack supports graphene electrodes, an AD8232-class "
                "front end, and a Bluetooth Low Energy radio. The firmware adapts gain "
                "to track electrode-skin impedance drift."
            ),
            "advantages": (
                "Seven-day wear without rehydration, no adhesive gel, and a 4 g patch "
                "that can be worn under clothing."
            ),
            "prior_art": (
                "Dry electrodes exist as separate metal or conductive-polymer pads "
                "connected by snap leads, which adds motion artefact."
            ),
            "keywords": "ECG, graphene, dry electrode, wearable, polyimide",
            "has_existing_drawings": True,
        },
    },
    {
        "key": "water-filter",
        "title": "Self-Cleaning Gravity Water Filter for Rural Households",
        "status": "Awaiting Patent Agent Acceptance",
        "team": "water",
        "owner": "priyangshumukherjee07@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 6,
        "details": {
            "invention_type": "Mechanical",
            "problem_statement": (
                "Gravity-fed ceramic filters clog within weeks and need manual "
                "scrubbing, so households stop using them."
            ),
            "proposed_solution": (
                "A backflush siphon cycles stored filtrate upward through the ceramic "
                "candle after every fourth fill, lifting sediment into a settling sump."
            ),
            "novelty_description": (
                "The backflush is driven by the head difference between two tanks and a "
                "float-triggered siphon, with no pump or electricity."
            ),
            "technical_description": (
                "Upper and lower tanks are separated by a ceramic candle. A float valve "
                "charges a 300 ml siphon chamber; when it trips, the stored water is "
                "forced back through the candle for 20 seconds."
            ),
            "advantages": (
                "Extends cleaning intervals from two weeks to three months and needs no "
                "power or replaceable media."
            ),
            "prior_art": (
                "Manual backflush filters use a hand pump or a bypass valve that the user "
                "must remember to operate."
            ),
            "keywords": "water filtration, ceramic candle, backflush, gravity filter",
            "has_existing_drawings": False,
        },
    },
    {
        "key": "prosthetic-knee",
        "title": "Low-Cost Prosthetic Knee with Adjustable Hydraulic Damping",
        "status": "Under Review",
        "team": "biomed",
        "owner": "mmanishablr@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 9,
        "details": {
            "invention_type": "Mechanical",
            "problem_statement": (
                "Hydraulic prosthetic knees cost several thousand dollars, so most "
                "transfemoral amputees in low-income settings receive a locked knee."
            ),
            "proposed_solution": (
                "A rotary hydraulic damper machined from standard aluminium tube is "
                "paired with a polyurethane seal and a cam that varies damping by "
                "flexion angle."
            ),
            "novelty_description": (
                "Damping is set by a single external grub screw that preloads a "
                "compressible insert in the return path, so a technician can tune the "
                "knee without opening the hydraulic circuit."
            ),
            "technical_description": (
                "The damper has a vane rotor and a fixed bypass orifice. A cam profile "
                "on the knee axis closes the orifice during stance and opens it during "
                "swing."
            ),
            "advantages": (
                "Under 90 USD in parts, serviceable with hand tools, and adjustable to "
                "the user's walking speed."
            ),
            "prior_art": (
                "Low-cost knees use friction brakes or manual locks, which give a stiff "
                "gait and high metabolic cost."
            ),
            "keywords": "prosthetic knee, hydraulic damping, low-cost, amputee",
            "has_existing_drawings": True,
        },
        "comments": (
            ("mmanishablr@gmail.com", "The cam profile needs a dimensioned drawing before this can move to drafting."),
            ("priyangshumukherjee07@gmail.com", "Agreed. I will add the stance-phase angles and the seal durometer."),
        ),
    },
    {
        "key": "millet-cutlery",
        "title": "Biodegradable Cutlery from Millet Husk Composite",
        "status": "Changes Requested",
        "team": "agri",
        "owner": "priyangshumukherjee07@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 12,
        "details": {
            "invention_type": "Chemical",
            "problem_statement": (
                "Single-use cutlery made from starch blends softens in hot food and "
                "leaves a chalky taste."
            ),
            "proposed_solution": (
                "Millet husk fibre is bound with a citric-acid crosslinked starch "
                "matrix and compression moulded at 140 degrees Celsius."
            ),
            "novelty_description": (
                "The husk is fractionated into long and short fibres; the long fraction "
                "forms a load-bearing skeleton while the short fraction fills the matrix."
            ),
            "technical_description": (
                "Husk is alkali-treated, washed, and split by sieving. The composite is "
                "pressed at 8 MPa for 90 seconds and cured for 24 hours."
            ),
            "advantages": (
                "Holds 90 degrees Celsius for 40 minutes, degrades in soil in 90 days, "
                "and uses an agricultural residue."
            ),
            "prior_art": (
                "Starch-based cutlery uses virgin starch and petrochemical binders, "
                "which raise cost and slow degradation."
            ),
            "keywords": "millet husk, biodegradable, cutlery, composite",
            "has_existing_drawings": False,
        },
        "comments": (
            ("mmanishablr@gmail.com", "Please add the fibre aspect ratio and the press cycle to the technical description."),
            ("priyangshumukherjee07@gmail.com", "Will add measured ratios from the pilot batch; the claims should mention the two-fraction mix."),
            ("mmanishablr@gmail.com", "Also confirm the 90-day degradation figure comes from a standard test, not an internal trial."),
        ),
    },
    {
        "key": "insulin-cooler",
        "title": "Smart Insulin Cooler for Last-Mile Delivery",
        "status": "Draft Generated",
        "team": "biomed",
        "owner": "mmanishablr@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 15,
        "drafts": True,
        "document": True,
        "details": {
            "invention_type": "Electronics",
            "problem_statement": (
                "Insulin loses potency when a delivery box drifts outside 2 to 8 "
                "degrees Celsius, and couriers have no way to prove the cold chain held."
            ),
            "proposed_solution": (
                "A vacuum-insulated box uses two eutectic gel packs and a thermoelectric "
                "trim heater, logging temperature to a sealed NFC tag that the recipient "
                "can read."
            ),
            "novelty_description": (
                "The controller heats as well as cools, so a single disposable pack "
                "keeps the chamber inside the 2 to 8 degree band instead of only "
                "preventing warming."
            ),
            "technical_description": (
                "An ESP32-class controller reads two DS18B20 probes, drives a Peltier "
                "element through an H-bridge, and writes signed readings to an NTAG "
                "213 every minute."
            ),
            "advantages": (
                "Twelve-hour holdover, an auditable cold-chain record, and a rechargeable "
                "pack that survives 500 cycles."
            ),
            "prior_art": (
                "Cold-chain boxes use passive gel packs and single-use indicator strips "
                "that show only whether a threshold was crossed."
            ),
            "keywords": "insulin, cold chain, thermoelectric, NFC, temperature logging",
            "has_existing_drawings": True,
        },
        "sections": {
            "ABSTRACT": (
                "A portable insulin cooler maintains a 2 to 8 degrees Celsius chamber "
                "using two eutectic gel packs and a thermoelectric trim stage. A "
                "microcontroller logs signed temperature readings to an NFC tag, giving "
                "the recipient a verifiable cold-chain record at handover."
            ),
            "BACKGROUND": (
                "Insulin is a peptide hormone that degrades when exposed to heat or "
                "repeated freezing. Last-mile delivery in warm climates often relies on "
                "a vacuum flask and a frozen gel pack, which can chill the vial below "
                "zero and denature it just as surely as heat.\n\n"
                "Existing data loggers are separate devices that couriers must remember "
                "to place in the box. They are rarely returned, so the record is lost "
                "exactly when a patient needs to know whether the dose is safe."
            ),
            "SUMMARY": (
                "The disclosed cooler combines passive insulation with active trimming. "
                "A Peltier element corrects both warm and cold excursions, while a "
                "sealed NFC tag stores a minute-by-minute record that any NFC phone can "
                "read without installing an app.\n\n"
                "Because the log is written by the same controller that drives the "
                "element, the record cannot be separated from the box that produced it."
            ),
            "DESCRIPTION": (
                "The enclosure is a vacuum-insulated shell with a 1.2 litre chamber. Two "
                "eutectic packs are frozen to minus 5 degrees Celsius before dispatch and "
                "clip into the lid; they provide coarse cooling, while the Peltier stage "
                "handles fine correction.\n\n"
                "A pair of DS18B20 probes measure chamber air and a vial surrogate. The "
                "controller samples every ten seconds, averages over a minute, and "
                "writes the value with an incrementing counter and a truncated HMAC to "
                "the tag. A red and green indicator show status without opening the lid.\n\n"
                "The Peltier element is driven through an H-bridge so the same hardware "
                "can heat or cool. A trim heater mode protects against freezing when the "
                "box is loaded with packs that are colder than planned."
            ),
            "CLAIMS": (
                "1. A portable medication cooler comprising an insulated chamber, a "
                "passive eutectic pack, a thermoelectric element, and a controller that "
                "selectively heats or cools the chamber to hold a target band.\n\n"
                "2. The cooler of claim 1, further comprising an NFC tag written by the "
                "controller with time-stamped temperature readings and an integrity "
                "value computed over those readings.\n\n"
                "3. The cooler of claim 1, wherein the controller averages samples over a "
                "fixed window before logging, reducing tag writes while preserving "
                "excursion evidence.\n\n"
                "4. The cooler of claim 2, wherein the tag is readable by a consumer "
                "phone without a dedicated application."
            ),
        },
    },
    {
        "key": "vaccine-box",
        "title": "Solar-Powered Cold Chain Box for Vaccine Transport",
        "status": "Ready for Filing",
        "team": "energy",
        "owner": "priyangshumukherjee07@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 18,
        "drafts": True,
        "document": True,
        "details": {
            "invention_type": "Electronics",
            "problem_statement": (
                "Vaccine carriers on two-wheelers lose cooling when the vehicle stops, "
                "and there is no record of the temperature history at the clinic."
            ),
            "proposed_solution": (
                "A phase-change panel is charged by a fold-out solar array during "
                "transit, and a low-power logger stores the temperature profile on the "
                "box itself."
            ),
            "novelty_description": (
                "The solar array folds over the lid in transit and doubles as a stand "
                "for the box at the clinic, so the same panel recharges the pack between "
                "deliveries."
            ),
            "technical_description": (
                "A 20 W fold-out panel charges a 12 V battery through an MPPT charger. A "
                "thermoelectric element and a phase-change panel hold the chamber at 4 "
                "degrees Celsius, and a logger records the profile."
            ),
            "advantages": (
                "Eight-hour holdover without sunlight, a reusable cold pack, and a "
                "temperature record that travels with the doses."
            ),
            "prior_art": (
                "Vaccine carriers use ice packs that are replaced at each stop and give "
                "no continuous record."
            ),
            "keywords": "vaccine, cold chain, solar, phase change, data logger",
            "has_existing_drawings": True,
        },
        "sections": {
            "ABSTRACT": (
                "A vaccine transport box holds a 2 to 8 degrees Celsius chamber using a "
                "phase-change panel charged by a fold-out solar array. The array folds "
                "over the lid during transit and unfolds as a stand at the clinic, where "
                "it recharges the panel between deliveries."
            ),
            "BACKGROUND": (
                "Routine immunisation in rural districts depends on carriers that keep "
                "vaccines cold for a single day. Ice packs are replaced at each health "
                "centre, and a missed replacement can freeze or warm the doses.\n\n"
                "Paper temperature strips record only the highest temperature reached. "
                "They cannot show how long a box was out of range, which is what a "
                "clinician needs to decide whether a vial is still usable."
            ),
            "SUMMARY": (
                "The box combines a rechargeable phase-change panel with a solar array "
                "that serves as both charger and stand. A logger records the chamber "
                "temperature for the life of the delivery and exposes it over a wired "
                "port at handover.\n\n"
                "The fold-out geometry keeps the panel in sunlight whenever the box is "
                "stationary, so holdover improves rather than degrades at the clinic."
            ),
            "DESCRIPTION": (
                "The body is a rotationally moulded shell with 40 mm of polyurethane "
                "insulation. A salt-hydrate panel lines the lid and is charged through a "
                "thermoelectric stage powered by the solar array or mains.\n\n"
                "The array is four hinged panels that fold flat over the lid for "
                "transport. Deployed, they form an A-frame that shades the box while "
                "charging the battery.\n\n"
                "A logger samples two probes every minute and stores a rolling 30-day "
                "record. At handover, a clinic worker connects a USB-C cable and exports "
                "the profile as a signed CSV."
            ),
            "CLAIMS": (
                "1. A transport container comprising an insulated chamber, a "
                "phase-change panel, a solar array movable between a stowed position "
                "over the lid and a deployed position, and a temperature logger.\n\n"
                "2. The container of claim 1, wherein the deployed array forms a stand "
                "that supports the container at an angle toward the sun.\n\n"
                "3. The container of claim 1, further comprising a thermoelectric stage "
                "that charges the phase-change panel from either the solar array or "
                "mains power.\n\n"
                "4. The container of claim 1, wherein the logger stores a rolling record "
                "and exports it as a signed file at handover."
            ),
        },
    },
    {
        "key": "pest-trap",
        "title": "AI-Assisted Pest Detection Trap for Small Farms",
        "status": "Filed",
        "team": "agri",
        "owner": "mmanishablr@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 24,
        "drafts": True,
        "document": True,
        "filing": {
            "application_number": "IN202641012345",
            "days_ago": 20,
        },
        "details": {
            "invention_type": "Electronics",
            "problem_statement": (
                "Small farms cannot afford scouting labour, so pest outbreaks are "
                "noticed only after visible crop damage."
            ),
            "proposed_solution": (
                "A pheromone trap carries a low-resolution camera and an on-device "
                "classifier that counts target insects and reports only the count over "
                "a long-range radio link."
            ),
            "novelty_description": (
                "The classifier runs on a microcontroller using a quantised model and "
                "wakes the camera only when a light gate detects an insect, giving "
                "months of battery life."
            ),
            "technical_description": (
                "An ESP32-S3 with a 0.3 MP sensor runs a 96 KB quantised network. A "
                "break-beam gate triggers capture, and counts are sent over LoRa twice a "
                "day."
            ),
            "advantages": (
                "Six-month battery life, no cloud subscription, and a per-trap count "
                "history that shows a outbreak building."
            ),
            "prior_art": (
                "Camera traps send every image to a server, which drains batteries and "
                "requires connectivity."
            ),
            "keywords": "pest detection, edge inference, pheromone trap, LoRa",
            "has_existing_drawings": True,
        },
        "sections": {
            "ABSTRACT": (
                "A pheromone trap counts target insects on-device. A break-beam gate "
                "wakes a low-resolution camera, a quantised classifier running on the "
                "trap's microcontroller counts insects in the frame, and only the count "
                "is transmitted over a long-range radio link."
            ),
            "BACKGROUND": (
                "Integrated pest management depends on early counts. On small holdings, "
                "scouting is done by hand and is the first task dropped when labour is "
                "short, so outbreaks are detected from damage rather than from trap "
                "catches.\n\n"
                "Connected camera traps exist, but transmitting every image needs a "
                "subscription and a power source that most fields do not have."
            ),
            "SUMMARY": (
                "The trap performs detection at the edge. A light gate avoids keeping "
                "the camera awake, and a compact model classifies the insects that "
                "enter the trap. The radio carries a count, not an image, which keeps "
                "both power draw and data cost low.\n\n"
                "Because images never leave the device, the trap also avoids storing "
                "pictures of the surrounding farm."
            ),
            "DESCRIPTION": (
                "The housing is a moulded funnel with a pheromone capsule and a "
                "transparent collection chamber. An infrared gate crosses the funnel "
                "mouth; when it is interrupted, the controller captures a frame.\n\n"
                "The classifier is a depthwise-separable network quantised to 8 bits and "
                "stored in flash. It distinguishes the target pest from beneficial "
                "insects and debris, and increments a counter only for target matches.\n\n"
                "Counts are buffered and transmitted twice daily over LoRa. The same "
                "radio acknowledges configuration changes, so a trap can be retuned "
                "without being opened."
            ),
            "CLAIMS": (
                "1. An insect trap comprising a housing, a pheromone lure, a light gate, "
                "a camera, and a controller that captures an image only when the gate is "
                "interrupted and classifies insects in that image on-device.\n\n"
                "2. The trap of claim 1, further comprising a radio that transmits only "
                "aggregated counts and receives configuration updates.\n\n"
                "3. The trap of claim 1, wherein the classifier is a quantised neural "
                "network stored in the controller's flash memory.\n\n"
                "4. The trap of claim 1, wherein the light gate and classifier together "
                "draw less energy than a continuously streaming camera."
            ),
        },
    },
    {
        "key": "leak-detector",
        "title": "Acoustic Leak Detector for Buried Water Pipelines",
        "status": "Hearing Scheduled",
        "team": "water",
        "owner": "priyangshumukherjee07@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 30,
        "document": False,
        "filing": {
            "application_number": "IN202541098765",
            "days_ago": 26,
        },
        "details": {
            "invention_type": "Electronics",
            "problem_statement": (
                "Municipal crews locate buried pipe leaks by walking routes with "
                "listening sticks, which misses small leaks and depends on operator "
                "hearing."
            ),
            "proposed_solution": (
                "A clamp-on sensor pod samples pipe-borne acoustic noise, computes a "
                "spectral signature, and reports the likelihood of a leak with its "
                "position between two pods."
            ),
            "novelty_description": (
                "Two pods time-stamp the same leak noise and the server resolves the "
                "position from the arrival difference, without excavating test holes."
            ),
            "technical_description": (
                "Each pod uses a piezoelectric contact microphone, a 24-bit ADC, and a "
                "GPS-disciplined clock. Cross-correlation runs on a low-power "
                "microcontroller before the result is uploaded."
            ),
            "advantages": (
                "Finds leaks below the hearing threshold, localises them to two metres, "
                "and needs no excavation to deploy."
            ),
            "prior_art": (
                "Correlating leak detectors exist as trolley-mounted systems that cost "
                "more than most municipal water boards can justify."
            ),
            "keywords": "leak detection, acoustics, cross-correlation, pipelines",
            "has_existing_drawings": True,
        },
        "comments": (
            ("mmanishablr@gmail.com", "The hearing date is confirmed. Please prepare the claim chart against the trolley systems."),
        ),
    },
    {
        "key": "sanitation",
        "title": "Waterless Sanitation Unit for Arid Regions",
        "status": "Granted",
        "team": "water",
        "owner": "mmanishablr@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 400,
        "filing": {
            "application_number": "IN202341076543",
            "days_ago": 380,
        },
        "details": {
            "invention_type": "Mechanical",
            "problem_statement": (
                "Pour-flush toilets in water-scarce districts are abandoned when the "
                "supply fails, and pit latrines fill within a few years."
            ),
            "proposed_solution": (
                "A urine-diverting dry toilet uses a solar chimney to drive moisture out "
                "of the vault and a removable cassette that composts waste in place."
            ),
            "novelty_description": (
                "The chimney draws air through the vault and across a blackened absorber, "
                "so the pile dries from below rather than forming a wet crust."
            ),
            "technical_description": (
                "The vault has a perforated floor over an air plenum. A 2 m chimney "
                "coated with selective absorber heats the air, and a baffle prevents "
                "odour from reaching the pan."
            ),
            "advantages": (
                "No water, no electricity, and compost removed every six months instead "
                "of a pit emptied every three years."
            ),
            "prior_art": (
                "Dry toilets rely on passive vents and manual bulking agents, which slow "
                "drying in humid conditions."
            ),
            "keywords": "dry toilet, solar chimney, composting, waterless sanitation",
            "has_existing_drawings": True,
        },
    },
    {
        "key": "awning",
        "title": "Retractable Solar Awning for City Buses",
        "status": "Abandoned",
        "team": "energy",
        "owner": "priyangshumukherjee07@gmail.com",
        "agent": None,
        "questionnaire": "completed",
        "created_days_ago": 60,
        "details": {
            "invention_type": "Mechanical",
            "problem_statement": (
                "Bus stop canopies are fixed, so they shade the queue at noon but not "
                "the low sun in the morning and evening."
            ),
            "proposed_solution": (
                "A canopy with flexible photovoltaic panels rolls out on a tracking arm "
                "that follows the sun's azimuth."
            ),
            "novelty_description": (
                "The roll-out panel doubles as the shade surface and charges a battery "
                "that powers the stop's lighting."
            ),
            "technical_description": (
                "A single-axis tracker drives a roller tube. Flexible panels are bonded "
                "to the canopy fabric and feed an MPPT charger."
            ),
            "advantages": "Shades the queue at any sun angle and offsets stop lighting.",
            "prior_art": "Fixed canopies and separate solar shelters.",
            "keywords": "solar awning, bus stop, tracking, flexible photovoltaic",
            "has_existing_drawings": False,
        },
    },
    # --- Aura Health Labs portfolio (mmanishablr only) --------------------
    # The shared teams above give both accounts the same view. These patents
    # live in a team only this account belongs to, and fill the lifecycle
    # stages the shared set does not cover for it.
    {
        "key": "exo-glove",
        "title": "Powered Grip Glove for Post-Stroke Hand Rehabilitation",
        "status": "Ready for Draft Generation",
        "team": "aura",
        "owner": "mmanishablr@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 11,
        "details": {
            "invention_type": "Electronics",
            "problem_statement": (
                "Hand therapy after a stroke needs hundreds of assisted repetitions, "
                "but clinic sessions are short and home exercises are unsupervised."
            ),
            "proposed_solution": (
                "A soft glove carries tendon-like cables driven by two micro-motors "
                "and senses grip force at the fingertips."
            ),
            "novelty_description": (
                "The controller detects when a patient attempts to close the hand and "
                "adds only the missing force, so the glove assists rather than moves "
                "the hand for them."
            ),
            "technical_description": (
                "Flex sensors along each finger feed a microcontroller that drives a "
                "pair of brushless motors through a cable sheath. Force-sensitive "
                "resistors at the fingertips close the loop, and a session log is "
                "written over Bluetooth."
            ),
            "advantages": (
                "Runs for a week on one charge, fits either hand, and records "
                "repetitions so a therapist can review progress remotely."
            ),
            "prior_art": (
                "Rehabilitation gloves either move the hand passively or use rigid "
                "exoskeleton linkages that are heavy and expensive."
            ),
            "keywords": "stroke rehabilitation, soft robotics, grip assist, glove",
            "has_existing_drawings": True,
        },
    },
    {
        "key": "hearing-aid",
        "title": "Self-Fitting Hearing Aid with In-Situ Audiogram",
        "status": "Awaiting Patent Agent Acceptance",
        "team": "aura",
        "owner": "mmanishablr@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 5,
        "details": {
            "invention_type": "Electronics",
            "problem_statement": (
                "Hearing aids need a professional fitting that costs more than the "
                "device in many districts, so users keep the factory profile."
            ),
            "proposed_solution": (
                "The aid plays calibrated tones through its own receiver, records the "
                "user's response, and derives a fitting prescription on the phone."
            ),
            "novelty_description": (
                "The audiogram and the fitting curve are produced in the same acoustic "
                "path that will be used for everyday listening, so no clinic "
                "audiometer or coupler is needed."
            ),
            "technical_description": (
                "A balanced-armature receiver and a MEMS microphone sit behind the "
                "earpiece. The phone app sweeps third-octave bands, the user taps when "
                "a tone is audible, and the resulting thresholds seed a wide-dynamic-"
                "range compression fitting."
            ),
            "advantages": (
                "Fits in twenty minutes at home, adapts the prescription to the actual "
                "ear canal, and can be refitted as hearing changes."
            ),
            "prior_art": (
                "Self-fitting aids exist but still rely on a calibrated headset or an "
                "in-clinic audiogram for the initial thresholds."
            ),
            "keywords": "hearing aid, audiogram, self-fitting, teleaudiology",
            "has_existing_drawings": True,
        },
    },
    {
        "key": "wound-dressing",
        "title": "Nanocellulose Wound Dressing with On-Demand Antimicrobial Release",
        "status": "Changes Requested",
        "team": "aura",
        "owner": "mmanishablr@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 14,
        "details": {
            "invention_type": "Chemical",
            "problem_statement": (
                "Chronic wounds are dressed for days at a time, and silver dressings "
                "release their antimicrobial whether or not an infection is present."
            ),
            "proposed_solution": (
                "A bacterial-cellulose sheet carries an antimicrobial in a pH-sensitive "
                "hydrogel that releases it only when wound fluid turns alkaline."
            ),
            "novelty_description": (
                "The release trigger is the pH shift produced by bacterial growth, so "
                "the dressing stays quiet on a healing wound and acts when an infection "
                "starts."
            ),
            "technical_description": (
                "Bacterial cellulose is impregnated with a chitosan-alginate hydrogel "
                "loaded with polyhexanide. The gel swells above pH 7.4, releasing the "
                "active agent; a colour indicator shows whether release has occurred."
            ),
            "advantages": (
                "Extends dressing changes to five days, uses a fraction of the "
                "antimicrobial, and gives a visible infection signal."
            ),
            "prior_art": (
                "Silver and iodine dressings release their payload continuously and "
                "must be changed on a fixed schedule."
            ),
            "keywords": "wound dressing, nanocellulose, pH-responsive, antimicrobial",
            "has_existing_drawings": False,
        },
        "comments": (
            (
                "mmanishablr@gmail.com",
                "The pH threshold needs a measured release curve, not just a claim.",
            ),
            (
                "priyangshumukherjee07@gmail.com",
                "I can add the buffer study; please also state the polyhexanide "
                "loading in mg per gram of dry cellulose.",
            ),
        ),
    },
    {
        "key": "bioreactor",
        "title": "Modular Single-Use Bioreactor for Distributed Vaccine Production",
        "status": "Ready for Filing",
        "team": "aura",
        "owner": "mmanishablr@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 22,
        "drafts": True,
        "document": True,
        "details": {
            "invention_type": "Biotechnology",
            "problem_statement": (
                "Vaccine manufacturing depends on large stainless-steel bioreactors, so "
                "production cannot be distributed to regional facilities."
            ),
            "proposed_solution": (
                "A single-use bag reactor clips into a reusable frame that provides "
                "mixing, aeration, and temperature control through the bag wall."
            ),
            "novelty_description": (
                "The impeller is magnetically coupled through a flexible pocket in the "
                "bag, so the bag stays sealed while the frame supplies all mechanics."
            ),
            "technical_description": (
                "A 50 litre single-use bag sits in a heated jacket. A magnetic drive in "
                "the base turns a disposable impeller, and a sparging line passes "
                "through a sterile connector. Sensors are clamped outside the bag."
            ),
            "advantages": (
                "Changeover takes an hour instead of a week, the frame is reused, and "
                "the same footprint scales from 50 to 500 litres."
            ),
            "prior_art": (
                "Single-use bags are mixed by rocking or by a shaft that enters through "
                "a rotary seal, which adds a contamination path."
            ),
            "keywords": "bioreactor, single-use, vaccine, magnetic coupling",
            "has_existing_drawings": True,
        },
        "sections": {
            "ABSTRACT": (
                "A modular bioreactor pairs a disposable bag with a reusable frame. A "
                "magnetic drive outside the bag turns a disposable impeller through a "
                "flexible pocket, and the frame supplies heating, aeration, and sensor "
                "clamps, so the fluid path stays closed."
            ),
            "BACKGROUND": (
                "Distributed vaccine production is limited by the cost and turnaround of "
                "stainless-steel bioreactors. A facility must be cleaned and validated "
                "between campaigns, which can take longer than the campaign itself.\n\n"
                "Single-use bags remove cleaning, but most designs still mix through a "
                "shaft and rotary seal, or rely on rocking motion that does not scale "
                "to dense cell cultures."
            ),
            "SUMMARY": (
                "The disclosed reactor separates the disposable fluid path from the "
                "mechanics. The bag carries only the impeller and a sterile sparge line; "
                "the frame carries the motor, heater, and sensors. Because the drive is "
                "magnetic and acts through a pocket in the bag, no shaft penetrates the "
                "sterile boundary.\n\n"
                "The same frame accepts bags of different volumes, so a regional "
                "facility can run small campaigns without a new installation."
            ),
            "DESCRIPTION": (
                "The frame is a welded stainless cabinet with a hinged lid and a "
                "removable bag cradle. The bag is a multi-layer film with a rigid base "
                "that houses the impeller and a flexible pocket aligned with the drive "
                "magnet.\n\n"
                "A magnetic coupling on the frame rotates the impeller at up to 300 rpm. "
                "Two Peltier-heated plates contact the bag sides, and a load cell under "
                "the cradle reports mass. Dissolved oxygen and pH probes are clamped into "
                "the bag's sensor ports from outside, so they can be removed without "
                "opening the fluid path.\n\n"
                "Aeration enters through a sterile connector and a sintered sparger at "
                "the bag base. Exhaust passes through a hydrophobic filter. The "
                "controller logs the run and refuses to start unless the bag lot and "
                "connector lot are recorded."
            ),
            "CLAIMS": (
                "1. A bioreactor comprising a reusable frame, a disposable bag carried "
                "by the frame, an impeller inside the bag, and a magnetic drive outside "
                "the bag that turns the impeller through a flexible pocket in the bag "
                "wall.\n\n"
                "2. The bioreactor of claim 1, wherein the frame further comprises "
                "heating plates and external sensor clamps that act on the bag without "
                "penetrating it.\n\n"
                "3. The bioreactor of claim 1, wherein the frame accepts bags of "
                "different volumes with the same drive and sensor geometry.\n\n"
                "4. The bioreactor of claim 1, further comprising a controller that "
                "records a bag lot identifier and a connector lot identifier before "
                "starting a run."
            ),
        },
    },
    {
        "key": "exoskeleton",
        "title": "Passive Shoulder Exoskeleton for Overhead Orchard Work",
        "status": "Examination Requested",
        "team": "aura",
        "owner": "mmanishablr@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 60,
        "drafts": True,
        "document": True,
        "filing": {"application_number": "IN202641023456", "days_ago": 20},
        "details": {
            "invention_type": "Mechanical",
            "problem_statement": (
                "Orchard workers hold their arms above shoulder height for hours, and "
                "the resulting shoulder injuries end careers early."
            ),
            "proposed_solution": (
                "A spring-balanced arm brace supports the forearm during overhead work "
                "and folds flat along the back when the arm is lowered."
            ),
            "novelty_description": (
                "The spring is engaged only above shoulder height by a cam that follows "
                "the upper-arm angle, so the brace does not resist reaching or carrying."
            ),
            "technical_description": (
                "A carbon-fibre link runs from a waist belt to a forearm cuff. A "
                "torsion spring in the shoulder joint is preloaded by a cam profile, and "
                "a ratchet lets the user lock the arm out of the way."
            ),
            "advantages": (
                "Weighs 1.4 kg, removes most of the arm's weight above the shoulder, "
                "and needs no battery or compressor."
            ),
            "prior_art": (
                "Powered exoskeletons support overhead work but cost thousands and need "
                "a battery; passive braces usually resist the full range of motion."
            ),
            "keywords": "exoskeleton, orchard, overhead work, spring balanced",
            "has_existing_drawings": True,
        },
        "sections": {
            "ABSTRACT": (
                "A passive shoulder exoskeleton supports the forearm during overhead "
                "work using a torsion spring engaged by a cam above shoulder height. "
                "Below that angle the brace folds along the back, leaving reaching and "
                "carrying unobstructed."
            ),
            "BACKGROUND": (
                "Overhead pruning and harvesting keep the shoulder in flexion for long "
                "periods. The load is small per motion but accumulates into rotator-cuff "
                "and impingement injuries.\n\n"
                "Powered exoskeletons can carry the arm, but their cost, battery, and "
                "maintenance keep them out of small orchards. Passive braces exist, but "
                "most provide constant force and fight the worker whenever the arm is "
                "lowered."
            ),
            "SUMMARY": (
                "The brace stores energy in a torsion spring and applies it only in the "
                "zone where the arm needs help. A cam on the shoulder joint engages the "
                "spring as the upper arm passes horizontal and releases it on the way "
                "down, so walking and carrying feel unencumbered.\n\n"
                "The structure is a waist belt, a shoulder link, and a forearm cuff, "
                "with no actuator or power source."
            ),
            "DESCRIPTION": (
                "The waist belt carries a vertical spine on the non-dominant side. A "
                "carbon-fibre upper link pivots at the shoulder, and a forearm cuff "
                "connects through a second pivot at the elbow.\n\n"
                "Inside the shoulder pivot, a torsion spring acts on a cam follower. The "
                "cam profile is shaped so the spring torque rises as the arm lifts above "
                "horizontal and falls to near zero below it. A friction damper smooths "
                "the transition.\n\n"
                "A ratchet at the shoulder lets the worker lock the brace upright while "
                "moving between trees. The cuff opens with a hook-and-loop strap so the "
                "brace can be put on with one hand."
            ),
            "CLAIMS": (
                "1. A passive shoulder exoskeleton comprising a waist belt, an upper-arm "
                "link, a forearm cuff, and a torsion spring engaged by a cam that "
                "applies support torque only when the upper arm is above a threshold "
                "angle.\n\n"
                "2. The exoskeleton of claim 1, wherein the cam releases the spring "
                "below the threshold angle so the arm moves freely.\n\n"
                "3. The exoskeleton of claim 1, further comprising a ratchet that locks "
                "the upper-arm link in an upright position.\n\n"
                "4. The exoskeleton of claim 1, wherein the links are carbon-fibre and "
                "the total mass is below two kilograms."
            ),
        },
    },
    {
        "key": "dialysis",
        "title": "Gravity-Assisted Peritoneal Dialysis Cycler for Home Use",
        "status": "FER Received",
        "team": "aura",
        "owner": "mmanishablr@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 150,
        "drafts": True,
        "document": True,
        "filing": {"application_number": "IN202541034567", "days_ago": 90},
        "details": {
            "invention_type": "Mechanical",
            "problem_statement": (
                "Peritoneal dialysis cyclers cost several thousand dollars and need "
                "reliable mains power, so home therapy is out of reach in many regions."
            ),
            "proposed_solution": (
                "A cycler uses gravity to drain and a low-power peristaltic pump only to "
                "fill, with a mechanical pinch valve sequencing the bags."
            ),
            "novelty_description": (
                "The drain cycle needs no pump at all: a float in the drain line opens "
                "the path only when the patient's cavity has enough head to empty, "
                "which removes the largest power draw."
            ),
            "technical_description": (
                "Three bags hang above the machine. A peristaltic pump fills through a "
                "heater plate, and a pinch valve array selects fill, dwell, or drain. A "
                "float sensor confirms drainage before the next fill."
            ),
            "advantages": (
                "Draws under 15 W, runs from a 12 V battery, and costs a fraction of a "
                "conventional cycler."
            ),
            "prior_art": (
                "Home cyclers use bidirectional pumps for fill and drain and require a "
                "stable mains supply; battery options are large and expensive."
            ),
            "keywords": "peritoneal dialysis, cycler, gravity drain, low power",
            "has_existing_drawings": True,
        },
        "sections": {
            "ABSTRACT": (
                "A peritoneal dialysis cycler fills with a low-power pump and drains by "
                "gravity through a float-controlled valve. Removing the drain pump "
                "reduces power draw enough to run the machine from a small battery."
            ),
            "BACKGROUND": (
                "Peritoneal dialysis lets patients treat at home, but the cycler is the "
                "most expensive part of the therapy. Most machines pump fluid in both "
                "directions, which sets the power requirement and the cost of the pump "
                "and its disposable cassette.\n\n"
                "In regions with unreliable mains power, a cycler must also run from a "
                "battery, and the drain pump is the largest load."
            ),
            "SUMMARY": (
                "The cycler keeps the fill pump but lets gravity empty the abdomen. A "
                "float in the drain line confirms that flow has started and that the "
                "cavity is empty before the next fill. A pinch-valve manifold selects "
                "the active bag, so one pump serves all fills.\n\n"
                "Because the drain path is passive, the machine can run from a 12 V "
                "battery for a full night."
            ),
            "DESCRIPTION": (
                "The housing has a hook for three solution bags and a heated plate for "
                "the fill line. A peristaltic pump moves fresh dialysate through the "
                "heater and into the patient line.\n\n"
                "The drain line runs from the patient connector to a waste bag below the "
                "machine. A float chamber in that line carries a magnet and a reed "
                "switch; the controller waits for the float to fall, which confirms "
                "drainage, before opening the next fill valve.\n\n"
                "A four-way pinch valve selects the active solution bag. The controller "
                "records fill volume, dwell time, and drain volume for each cycle and "
                "stops if the drained volume falls below a threshold."
            ),
            "CLAIMS": (
                "1. A peritoneal dialysis cycler comprising a fill pump, a heater, a "
                "plurality of solution bags, a drain line, and a float sensor in the "
                "drain line that confirms gravity drainage before a subsequent fill.\n\n"
                "2. The cycler of claim 1, further comprising a pinch-valve manifold "
                "that selects among the solution bags with a single fill pump.\n\n"
                "3. The cycler of claim 1, wherein the drain line has no pump and the "
                "controller treats a drain volume below a threshold as a fault.\n\n"
                "4. The cycler of claim 1, wherein the fill pump and controller run from "
                "a 12 V battery."
            ),
        },
    },
    {
        "key": "surgical-drill",
        "title": "Single-Use Surgical Drill with Mechanical Torque Limiter",
        "status": "Rejected",
        "team": "aura",
        "owner": "mmanishablr@gmail.com",
        "agent": "mmanishablr@gmail.com",
        "questionnaire": "completed",
        "created_days_ago": 300,
        "filing": {"application_number": "IN202341045678", "days_ago": 200},
        "details": {
            "invention_type": "Mechanical",
            "problem_statement": (
                "Reusable surgical drills need sterilisation between cases, and a "
                "worn clutch can overheat bone without warning."
            ),
            "proposed_solution": (
                "A single-use drill body carries a ball-detent torque limiter that "
                "slips at a fixed threshold and cannot be adjusted or reused."
            ),
            "novelty_description": (
                "The limiter is moulded into the disposable gearbox, so its threshold "
                "is set at manufacture and the drill cannot be reprocessed with a "
                "different setting."
            ),
            "technical_description": (
                "A planetary gearbox drives the chuck through a spring-loaded ball "
                "detent. When torque exceeds the threshold, the balls ride out of their "
                "seats and the drive slips. The housing is a sealed polymer unit."
            ),
            "advantages": (
                "Removes sterilisation from the workflow and gives a consistent torque "
                "limit for every case."
            ),
            "prior_art": (
                "Reusable drills use adjustable clutches that can drift after "
                "sterilisation cycles."
            ),
            "keywords": "surgical drill, torque limiter, single-use, sterilisation",
            "has_existing_drawings": True,
        },
    },
    {
        "key": "cooling-vest",
        "title": "Phase-Change Cooling Vest for Foundry Workers",
        "status": "Withdrawn",
        "team": "aura",
        "owner": "mmanishablr@gmail.com",
        "agent": None,
        "questionnaire": "completed",
        "created_days_ago": 80,
        "details": {
            "invention_type": "Mechanical",
            "problem_statement": (
                "Foundry workers wear heavy protective clothing near furnaces and "
                "cannot drink enough water to stay cool."
            ),
            "proposed_solution": (
                "A vest carries flat phase-change pouches against the torso and "
                "recharges them in a chilled dock between shifts."
            ),
            "novelty_description": (
                "The pouches are segmented so the vest stays flexible when frozen and "
                "the melting front moves toward the chest rather than the edges."
            ),
            "technical_description": (
                "Pouches of a salt hydrate with a 28 degree melting point sit in "
                "pockets over the torso. A dock circulates chilled water through the "
                "pouches to recharge them in 25 minutes."
            ),
            "advantages": (
                "Adds two hours of comfortable work in radiant heat without a tether "
                "or battery."
            ),
            "prior_art": (
                "Ice vests are heavy, wet, and lose cooling within an hour; "
                "compressor vests need a tether."
            ),
            "keywords": "cooling vest, phase change, foundry, heat stress",
            "has_existing_drawings": False,
        },
    },
)

APPLICANTS = (
    {
        "full_name_or_org_name": "Kridhata Ventures Private Limited",
        "applicant_type": "Organization",
        "address": "22, 4th Cross, Jayanagar, Bengaluru 560041",
        "country": "India",
        "postal_code": "560041",
    },
)

INVENTOR_NAMES = {
    "priyangshumukherjee07@gmail.com": "Priyangshu Mukherjee",
    "mmanishablr@gmail.com": "Aura Fla",
}


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _days_ago(days: float) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(days=days))


def _put(collection: str, doc_id: str, data: dict) -> bool:
    """Create a seeded document unless it already exists. Returns created?"""
    ref = db().collection(collection).document(doc_id)
    if ref.get().exists:
        return False
    payload = {**data, "demo_seed": SEED_TAG}
    create_doc(collection, payload, doc_id=doc_id)
    return True


def load_users() -> dict[str, dict]:
    users: dict[str, dict] = {}
    for email in USER_EMAILS:
        matches = [
            doc
            for doc in query_docs("users")
            if (doc.get("email") or "").lower() == email.lower()
        ]
        if not matches:
            raise SystemExit(
                f"No Firestore profile for {email}. Sign in with that Google "
                "account once, then run the seed again."
            )
        users[email] = matches[0]
    return users


def seed_teams(users: dict[str, dict]) -> dict[str, str]:
    team_ids: dict[str, str] = {}
    for team in TEAMS:
        doc_id = f"demo-team-{team['key']}"
        team_ids[team["key"]] = doc_id
        _put(
            "teams",
            doc_id,
            {
                "team_name": team["name"],
                "team_status": "Active",
                "created_by": users[USER_EMAILS[0]]["id"],
                "created_at": _days_ago(90),
            },
        )
        for email in team.get("members", TEAM_MEMBERS):
            member_id = users[email]["id"]
            db().collection("teams").document(doc_id).collection("members").document(
                member_id
            ).set(
                {
                    "user_id": member_id,
                    "membership_status": "Active",
                    "added_by": users[USER_EMAILS[0]]["id"],
                    "created_at": _days_ago(90),
                    "demo_seed": SEED_TAG,
                },
                merge=True,
            )
    return team_ids


def _patent_document(patent: dict, users: dict[str, dict], team_id: str) -> dict:
    owner = users[patent["owner"]]["id"]
    agent = users[patent["agent"]]["id"] if patent.get("agent") else None
    status = patent["status"]
    questionnaire_status = (
        "Completed" if patent["questionnaire"] == "completed" else "In Progress"
    )
    filing = patent.get("filing") or {}
    return {
        "team_id": team_id,
        "invention_title": patent["title"],
        "application_status": status,
        "assigned_patent_agent_id": agent,
        "ai_status": "Completed" if patent.get("drafts") else "Not Started",
        "questionnaire_status": questionnaire_status,
        "document_status": "Generated" if patent.get("document") else "Not Started",
        "filing_status": "Filed" if filing else "Not Started",
        "official_application_number": filing.get("application_number"),
        "filing_date": _days_ago(filing["days_ago"]) if filing else None,
        "created_by": owner,
        "created_at": _days_ago(patent["created_days_ago"]),
    }


def seed_patents(users: dict[str, dict], team_ids: dict[str, str]) -> dict[str, dict]:
    patents: dict[str, dict] = {}
    for patent in PATENTS:
        doc_id = f"demo-patent-{patent['key']}"
        _put(
            "patents",
            doc_id,
            _patent_document(patent, users, team_ids[patent["team"]]),
        )
        patents[patent["key"]] = {"id": doc_id, **patent}
    return patents


def seed_questionnaires(
    users: dict[str, dict], patents: dict[str, dict]
) -> None:
    for key, patent in patents.items():
        details = dict(patent["details"])
        fields = {
            "invention_type",
            "problem_statement",
            "proposed_solution",
            "novelty_description",
            "technical_description",
        }
        filled = sum(1 for field in fields if details.get(field))
        if patent["questionnaire"] == "completed":
            status, percentage = "Completed", "100.00"
        else:
            status = "In Progress" if filled else "Not Started"
            percentage = f"{100.0 * filled / len(fields):.2f}"
        doc_id = f"demo-questionnaire-{key}"
        _put(
            "questionnaires",
            doc_id,
            {
                "patent_application_id": patent["id"],
                "questionnaire_status": status,
                "completion_percentage": percentage,
                **details,
                "created_at": _days_ago(patent["created_days_ago"]),
            },
        )
        if patent["questionnaire"] != "completed":
            continue
        _put(
            "questionnaire_versions",
            f"{doc_id}-v1",
            {
                "questionnaire_id": doc_id,
                "patent_application_id": patent["id"],
                "version_number": 1,
                "version_status": "Completed",
                "change_reason": "Submitted by the applicant",
                "created_by": users[patent["owner"]]["id"],
                **details,
                "created_at": _days_ago(patent["created_days_ago"] - 0.5),
            },
        )


def seed_parties(users: dict[str, dict], patents: dict[str, dict]) -> None:
    for key, patent in patents.items():
        applicant = APPLICANTS[0]
        _put(
            "applicants",
            f"demo-applicant-{key}-1",
            {
                "patent_application_id": patent["id"],
                "applicant_type": applicant["applicant_type"],
                "full_name_or_org_name": applicant["full_name_or_org_name"],
                "address": applicant["address"],
                "country": applicant["country"],
                "postal_code": applicant["postal_code"],
                "email": "ip@kridhata.example",
                "phone": "+91 80 4000 0000",
                "is_primary": True,
                "display_order": 0,
            },
        )
        owner_email = patent["owner"]
        inventor_emails = [owner_email]
        if patent.get("agent") and patent["agent"] != owner_email:
            inventor_emails.append(patent["agent"])
        for order, email in enumerate(inventor_emails):
            _put(
                "inventors",
                f"demo-inventor-{key}-{order + 1}",
                {
                    "patent_application_id": patent["id"],
                    "user_id": users[email]["id"],
                    "full_name": INVENTOR_NAMES[email],
                    "address": "Bengaluru, Karnataka",
                    "country": "India",
                    "postal_code": "560041",
                    "email": email,
                    "phone": None,
                    "inventor_order": order,
                },
            )


def seed_drafts(users: dict[str, dict], patents: dict[str, dict]) -> None:
    for key, patent in patents.items():
        if not patent.get("drafts"):
            continue
        questionnaire_id = f"demo-questionnaire-{key}"
        version_id = f"{questionnaire_id}-v1"
        for section in SECTION_TYPES:
            _put(
                "drafts",
                f"demo-draft-{key}-{section}",
                {
                    "patent_application_id": patent["id"],
                    "questionnaire_version_id": version_id,
                    "section_type": section,
                    "version_number": 1,
                    "ai_provider": "demo",
                    "ai_model": "seeded-demo",
                    "ai_response": patent["sections"][section],
                    "processing_status": "Completed",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "created_at": _days_ago(patent["created_days_ago"] - 1),
                },
            )


def _docx_sections(patent: dict) -> dict[str, str]:
    return patent.get("sections") or {}


def seed_documents(users: dict[str, dict], patents: dict[str, dict]) -> None:
    document_type = "Patent Application"
    for key, patent in patents.items():
        if not patent.get("document"):
            continue
        patent_row = {
            "id": patent["id"],
            "invention_title": patent["title"],
            "application_status": patent["status"],
        }
        docx = documents.render_docx(patent_row, _docx_sections(patent), None)
        blob_id = f"demo-blob-{key}-docx"
        existing = db().collection("blobs").document(blob_id).get()
        if not existing.exists:
            blobs.put_blob(docx, documents.DOCX_MIME, blob_id=blob_id)
            patch_doc("blobs", blob_id, {"demo_seed": SEED_TAG})
        generated_by = users[patent["agent"] or patent["owner"]]["id"]
        stamp = _days_ago(patent["created_days_ago"] - 1.5)
        document_id = f"{patent['id']}:{document_type}:DOCX"
        _put(
            "documents",
            document_id,
            {
                "patent_application_id": patent["id"],
                "document_type": document_type,
                "output_format": "DOCX",
                "watermark_status": "DRAFT",
                "template_id": None,
                "generated_by": generated_by,
                "generated_at": stamp,
                "stored_path": blob_id,
                "file_size_bytes": len(docx),
                "latest_version": 1,
            },
        )
        _put(
            "document_versions",
            f"demo-document-version-{key}-1",
            {
                "document_id": document_id,
                "patent_application_id": patent["id"],
                "version_number": 1,
                "change_summary": "Generated DOCX",
                "generated_by": generated_by,
                "generated_at": stamp,
                "storage_path": blob_id,
                "file_size_bytes": len(docx),
            },
        )
        _put(
            "document_jobs",
            f"demo-document-job-{key}",
            {
                "patent_application_id": patent["id"],
                "status": "Completed",
                "output_format": "DOCX",
                "triggered_by": generated_by,
                "retried_from_job_id": None,
                "error_message": None,
                "started_at": stamp,
                "completed_at": stamp,
                "created_at": stamp,
            },
        )
        _put(
            "document_counters",
            f"{patent['id']}:DOCX:{document_type}",
            {"next_version": 1},
        )


def seed_collaboration(users: dict[str, dict], patents: dict[str, dict]) -> None:
    activity: list[tuple[str, str, str, str, str]] = []
    notifications: list[tuple[str, str, str, bool, str]] = []
    events: list[tuple[str, str, str, str]] = []
    assignments: list[tuple[str, str | None, str, str, str, str]] = []

    for key, patent in patents.items():
        owner_id = users[patent["owner"]]["id"]
        agent_id = users[patent["agent"]]["id"] if patent.get("agent") else None
        created = _days_ago(patent["created_days_ago"])
        activity.append((owner_id, "PatentCreated", "PatentApplication", patent["id"], created))

        if patent["questionnaire"] == "completed":
            activity.append(
                (owner_id, "QuestionnaireSubmitted", "PatentApplication", patent["id"], created)
            )
        if patent["status"] != "Draft":
            activity.append(
                (owner_id, "PatentSubmitted", "PatentApplication", patent["id"], created)
            )
        if agent_id:
            assignments.append(
                (
                    patent["id"],
                    None,
                    agent_id,
                    "Initial assignment",
                    owner_id,
                    _days_ago(patent["created_days_ago"] - 0.5),
                )
            )
            activity.append(
                (owner_id, "AgentAssigned", "PatentApplication", patent["id"], created)
            )
            notifications.append(
                (
                    agent_id,
                    patent["id"],
                    "Assigned",
                    patent["status"] != "Awaiting Patent Agent Acceptance",
                    _days_ago(patent["created_days_ago"] - 0.5),
                )
            )
        if patent.get("drafts"):
            activity.append(
                (agent_id or owner_id, "DraftGenerated", "PatentApplication", patent["id"], created)
            )
        if patent.get("document"):
            activity.append(
                (
                    agent_id or owner_id,
                    "DocumentGenerated",
                    "PatentApplication",
                    patent["id"],
                    created,
                )
            )
        filing = patent.get("filing")
        if filing:
            activity.append(
                (
                    owner_id,
                    "FilingRecorded",
                    "PatentApplication",
                    patent["id"],
                    _days_ago(filing["days_ago"]),
                )
            )
            notifications.append(
                (
                    owner_id,
                    patent["id"],
                    "FilingRecorded",
                    True,
                    _days_ago(filing["days_ago"]),
                )
            )
        if filing and patent["status"] in {"Filed", "Hearing Scheduled", "Granted"}:
            events.append(
                (
                    patent["id"],
                    "Filing Deadline",
                    _iso(datetime.now(timezone.utc) + timedelta(days=5 + len(events) * 9)),
                    owner_id,
                )
            )
        if patent["status"] == "Hearing Scheduled":
            events.append(
                (
                    patent["id"],
                    "Hearing",
                    _iso(datetime.now(timezone.utc) + timedelta(days=12)),
                    owner_id,
                )
            )
        if patent["status"] == "Under Review":
            events.append(
                (
                    patent["id"],
                    "Reminder",
                    _iso(datetime.now(timezone.utc) + timedelta(days=3)),
                    agent_id or owner_id,
                )
            )
        if patent["status"] == "Ready for Filing":
            events.append(
                (
                    patent["id"],
                    "Filing Deadline",
                    _iso(datetime.now(timezone.utc) + timedelta(days=9)),
                    owner_id,
                )
            )
        if patent["status"] == "Examination Requested":
            events.append(
                (
                    patent["id"],
                    "Examination",
                    _iso(datetime.now(timezone.utc) + timedelta(days=21)),
                    owner_id,
                )
            )
        if patent["status"] in {"FER Received", "FER Response Submitted"}:
            events.append(
                (
                    patent["id"],
                    "Reminder",
                    _iso(datetime.now(timezone.utc) + timedelta(days=14)),
                    owner_id,
                )
            )
        if patent["status"] == "Granted":
            notifications.append(
                (owner_id, patent["id"], "Granted", False, _days_ago(30))
            )
        if patent["status"] == "Changes Requested":
            notifications.append(
                (owner_id, patent["id"], "ChangeRequested", False, created)
            )
        for index, (author_email, text) in enumerate(patent.get("comments", ())):
            author_id = users[author_email]["id"]
            _put(
                "comments",
                f"demo-comment-{key}-{index + 1}",
                {
                    "patent_application_id": patent["id"],
                    "user_id": author_id,
                    "comment_text": text,
                    "created_at": _days_ago(patent["created_days_ago"] - 1 - index * 0.2),
                },
            )
            if author_id != owner_id:
                notifications.append(
                    (
                        owner_id,
                        patent["id"],
                        "CommentAdded",
                        index > 0,
                        _days_ago(patent["created_days_ago"] - 1 - index * 0.2),
                    )
                )

    # An admin-visible submission notification and one reassignment history row
    # so the audit views are not empty for the Super Admin account.
    admin_id = users[USER_EMAILS[0]]["id"]
    notifications.append(
        (admin_id, patents["ecg-patch"]["id"], "Submitted", False, _days_ago(3.5))
    )
    notifications.append(
        (admin_id, patents["solar-cooker"]["id"], "CommentAdded", True, _days_ago(1))
    )
    if patents["millet-cutlery"].get("agent"):
        assignments.append(
            (
                patents["millet-cutlery"]["id"],
                users[patents["millet-cutlery"]["agent"]]["id"],
                users[patents["millet-cutlery"]["agent"]]["id"],
                "Reassigned to balance workload",
                admin_id,
                _days_ago(10),
            )
        )

    # IDs are derived from the record content, not a running index: adding a
    # patent later must not renumber (and therefore skip or overwrite) the
    # seeded activity/notification rows of the patents before it.
    for user_id, event_type, entity_type, entity_id, stamp in activity:
        _put(
            "activity",
            f"demo-activity-{entity_id}-{event_type}",
            {
                "user_id": user_id,
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "created_at": stamp,
            },
        )
    notification_counts: dict[tuple[str, str, str], int] = {}
    for user_id, patent_id, notification_type, is_read, stamp in notifications:
        counter_key = (patent_id, notification_type, user_id or "")
        notification_counts[counter_key] = notification_counts.get(counter_key, 0) + 1
        _put(
            "notifications",
            f"demo-notification-{patent_id}-{notification_type.lower()}-"
            f"{user_id}-{notification_counts[counter_key]}",
            {
                "user_id": user_id,
                "patent_application_id": patent_id,
                "notification_type": notification_type,
                "is_read": is_read,
                "created_at": stamp,
            },
        )
    for patent_id, event_type, event_date, created_by in events:
        _put(
            "calendar_events",
            f"demo-calendar-{patent_id}-{event_type}",
            {
                "patent_application_id": patent_id,
                "event_type": event_type,
                "event_date": event_date,
                "created_by": created_by,
            },
        )
    assignment_counts: dict[str, int] = {}
    for patent_id, from_agent, to_agent, reason, changed_by, stamp in assignments:
        assignment_counts[patent_id] = assignment_counts.get(patent_id, 0) + 1
        _put(
            "assignment_history",
            f"demo-assignment-{patent_id}-{assignment_counts[patent_id]}",
            {
                "patent_application_id": patent_id,
                "from_agent_id": from_agent,
                "to_agent_id": to_agent,
                "reason": reason,
                "changed_by": changed_by,
                "created_at": stamp,
            },
        )


def reset() -> int:
    """Delete every document carrying the seed tag. Returns the count."""
    removed = 0
    for collection_name in SEEDED_COLLECTIONS:
        docs = query_docs(
            collection_name, filters=[("demo_seed", "==", SEED_TAG)]
        )
        for doc in docs:
            if collection_name == "teams":
                members = (
                    db()
                    .collection("teams")
                    .document(doc["id"])
                    .collection("members")
                    .stream()
                )
                for member in members:
                    member.reference.delete()
                    removed += 1
            db().collection(collection_name).document(doc["id"]).delete()
            removed += 1
    return removed


def seed() -> None:
    users = load_users()
    team_ids = seed_teams(users)
    patents = seed_patents(users, team_ids)
    seed_questionnaires(users, patents)
    seed_parties(users, patents)
    seed_drafts(users, patents)
    seed_documents(users, patents)
    seed_collaboration(users, patents)
    print(f"Seeded {len(patents)} patents across {len(team_ids)} teams.")
    print("Open the app and sign in as either account to see the data.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the plan only")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete the seeded records first, then seed again",
    )
    parser.add_argument(
        "--reset-only",
        action="store_true",
        help="delete the seeded records and stop",
    )
    args = parser.parse_args()

    if settings.environment.lower() == "production":
        print("Refusing to seed a production environment.", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"Would seed {len(PATENTS)} patents into: {', '.join(USER_EMAILS)}")
        for patent in PATENTS:
            print(
                f"  - {patent['status']:<32} {patent['title']} "
                f"({len(patent.get('sections') or {})} draft sections)"
            )
        return 0

    initialize_firebase()
    if args.reset or args.reset_only:
        print(f"Removed {reset()} seeded documents.")
        if args.reset_only:
            return 0
    seed()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
