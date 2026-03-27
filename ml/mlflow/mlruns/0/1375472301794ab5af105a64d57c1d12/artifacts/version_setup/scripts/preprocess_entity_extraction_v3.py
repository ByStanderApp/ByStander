
import re
def preprocess(query, params=None):
    print(f"[SCRIPT preprocess_entity_extraction_v3.py] Extracting entities from: {query}")
    location_keywords = re.findall(r"at (\w+ \w+)|near (\w+ \w+)", query)
    locations = [l[0] or l[1] for l in location_keywords if l[0] or l[1]]
    entities = {"locations": locations, "raw_query": query}
    if "fire" in query.lower():
        entities["emergency_type"] = "Fire"
    elif "accident" in query.lower():
        entities["emergency_type"] = "Traffic Accident"
    else:
        entities["emergency_type"] = "Unknown"
    return entities