from pydantic import BaseModel
from typing import List, Optional

class Subgenre(BaseModel):
    """
    Defines a specific subgenre with its corresponding
    project-specific filter tags.
    """
    name: str
    description: str
    # These fields map to your project filters
    setting: Optional[str] = None
    themes: Optional[List[str]] = None
    tropes: Optional[List[str]] = None
    main_character: Optional[str] = None
    time_period: Optional[str] = None

class Genre(BaseModel):
    """
    Defines a top-level "Umbrella" Genre, which contains
    a list of its subgenres.
    """
    umbrella: str  # e.g., "Speculative Fiction", "Realistic/Commercial"
    name: str  # e.g., "Fantasy", "Science Fiction"
    description: str
    subgenres: List[Subgenre]

# --- 1. FANTASY (SPECULATIVE) ---
fantasy_subgenres = [
    Subgenre(
        name="Epic/High Fantasy",
        description="Set entirely in a fictional world; involves a grand, world-saving quest.",
        setting="Other World"
    ),
    Subgenre(
        name="Urban Fantasy",
        description="Magic/supernatural elements intrude on a recognizable, modern, city setting.",
        setting="City"
    ),
    Subgenre(
        name="Dark Fantasy / Grimdark",
        description="Focuses on morally ambiguous characters, violence, and dark themes; often blends with horror.",
        themes=["Dark"]
    ),
    Subgenre(
        name="Sword and Sorcery",
        description="Focuses on a single hero's personal, episodic adventures and martial skill.",
        tropes=["Hero's Quest", "Adventure"]
    ),
    Subgenre(
        name="Historical Fantasy",
        description="Set in a recognizable historical period but includes magical elements.",
        time_period="Historical"
    ),
    Subgenre(
        name="Magical Realism",
        description="Magical elements blend seamlessly into an otherwise realistic, modern setting.",
        setting="Real World"
    ),
]

# --- 2. SCIENCE FICTION (SPECULATIVE) ---
sci_fi_subgenres = [
    Subgenre(
        name="Cyberpunk",
        description="Focuses on advanced technology and social decay (High-tech, low-life).",
        setting="City",
        time_period="Futuristic"
    ),
    Subgenre(
        name="Dystopian",
        description="Explores oppressive, nightmarish future societies.",
        themes=["Societal Oppression"]
    ),
    Subgenre(
        name="Space Opera",
        description="Sweeping, dramatic adventures in space, often involving empires and warfare.",
        setting="Space/Futuristic"
    ),
    Subgenre(
        name="Steampunk",
        description="Technology based on 19th-century steam power (often Victorian era setting).",
        time_period="Historical"
    ),
    Subgenre(
        name="Hard Sci-Fi",
        description="Focuses rigorously on scientific accuracy and plausibility.",
        themes=["Scientific Accuracy"]
    ),
    Subgenre(
        name="Military Sci-Fi",
        description="Focuses on interstellar or futuristic warfare and military themes.",
        themes=["War/Conflict"]
    ),
]

# --- 3. HORROR (SPECULATIVE) ---
horror_subgenres = [
    Subgenre(
        name="Supernatural/Paranormal",
        description="Focuses on ghosts, demons, vampires, or the occult.",
        tropes=["Hauntings", "Monsters"]
    ),
    Subgenre(
        name="Psychological Horror",
        description="Focuses on mental and emotional stress, often blurring the line between reality and madness.",
        themes=["Mental Instability"]
    ),
    Subgenre(
        name="Body Horror",
        description="Focuses on graphic violence, disfigurement, or unnatural transformations of the human body.",
        themes=["Physical Gore"]
    ),
    Subgenre(
        name="Gothic Horror",
        description="Characterized by a gloomy setting (old castles/manors) and atmosphere of decay.",
        setting="Old Manor/Castle"
    ),
]

# --- 4. MYSTERY / CRIME (REALISTIC) ---
mystery_subgenres = [
    Subgenre(
        name="Cozy Mystery",
        description="Gentle, amateur sleuths, no explicit sex or violence, usually set in a charming town.",
        themes=["Low-stakes Crime"]
    ),
    Subgenre(
        name="Police Procedural",
        description="Focuses accurately on the step-by-step methods of a police investigation.",
        main_character="Police Officer"
    ),
    Subgenre(
        name="Noir / Hardboiled",
        description="Cynical, morally ambiguous detective in a corrupt, urban setting.",
        setting="City",
        themes=["Dark"]
    ),
    Subgenre(
        name="Historical Mystery",
        description="A crime solved in a specific, recognizable past time period.",
        time_period="Historical"
    ),
    Subgenre(
        name="Caper / Crime Thriller",
        description="Focuses on the planning and execution of the crime itself (from the criminal's perspective).",
        main_character="Criminal"
    ),
]

# --- 5. THRILLER / SUSPENSE (REALISTIC) ---
thriller_subgenres = [
    Subgenre(
        name="Psychological Thriller",
        description="Tension derived from the characters' unstable mental states or manipulation.",
        themes=["Mental Conflict"]
    ),
    Subgenre(
        name="Espionage / Spy Thriller",
        description="Focuses on spies, covert operations, and political intrigue.",
        tropes=["Covert Operations"]
    ),
    Subgenre(
        name="Legal/Medical Thriller",
        description="Tension centers around a high-stakes legal case or a crisis in the medical field.",
        setting="Courtroom/Hospital"
    ),
    Subgenre(
        name="Techno-Thriller",
        description="Danger stems from a real-world scientific or technological crisis.",
        themes=["Technology"]
    ),
]

# --- 6. ROMANCE (REALISTIC/COMMERCIAL) ---
romance_subgenres = [
    Subgenre(
        name="Contemporary Romance",
        description="Set in the present day with realistic, modern characters and scenarios.",
        time_period="Contemporary"
    ),
    Subgenre(
        name="Historical Romance",
        description="Set in a recognizable historical period (often Regency, Victorian).",
        time_period="Historical"
    ),
    Subgenre(
        name="Paranormal Romance",
        description="Features supernatural beings and the romantic relationship is central.",
        main_character="Supernatural"
    ),
    Subgenre(
        name="Romantic Suspense",
        description="Blends romance with elements of danger, crime, or mystery.",
        themes=["Danger/Intrigue"]
    ),
    Subgenre(
        name="Erotica / Erotic Romance",
        description="Focuses explicitly on the sexual relationship between the characters.",
        tropes=["Explicit Content"]
    ),
    Subgenre(
        name="Romantic Comedy",
        description="Uses humor and lighthearted situations to bring the couple together.",
        themes=["Humorous"]
    ),
]

# --- 7. OTHER FICTION CATEGORIES ---
# (We'll model these as their own genres for simplicity)
other_fiction_genres = [
    Genre(
        umbrella="Other Fiction",
        name="Historical Fiction",
        description="Set in the past (usually pre-1950) with fictional characters interacting with real events/figures.",
        subgenres=[Subgenre(name="Historical Fiction", description="N/A", time_period="Historical")]
    ),
    Genre(
        umbrella="Other Fiction",
        name="Action & Adventure",
        description="Focuses on a risk-filled journey, exploration, or high-stakes physical conflict.",
        subgenres=[Subgenre(name="Action & Adventure", description="N/A", tropes=["Hero's Journey"])]
    ),
    Genre(
        umbrella="Other Fiction",
        name="Literary Fiction",
        description="Emphasizes prose, style, character development, and theme over plot.",
        subgenres=[Subgenre(name="Literary Fiction", description="N/A", themes=["Character-driven"])]
    ),
    Genre(
        umbrella="Other Fiction",
        name="Young Adult (YA)",
        description="Protagonist is usually a teenager (12-18); can be any genre.",
        subgenres=[Subgenre(name="Young Adult (YA)", description="N/A", main_character="Teen")] # We can map Age Group to MC
    ),
    Genre(
        umbrella="Other Fiction",
        name="Middle Grade (MG)",
        description="Targeted at readers aged 8-12; simpler themes and generally lighter tone.",
        subgenres=[Subgenre(name="Middle Grade (MG)", description="N/A", main_character="Child")] # We can map Age Group to MC
    ),
    Genre(
        umbrella="Other Fiction",
        name="Women's Fiction",
        description="Focuses on the female protagonist's emotional journey, growth, and relationships.",
        subgenres=[Subgenre(name="Women's Fiction", description="N/A", main_character="Female")]
    ),
]


# --- THE FINAL COMPILED LIST OF ALL FICTION GENRES ---
FICTION_GENRES: List[Genre] = [
    Genre(
        umbrella="Speculative Fiction",
        name="Fantasy",
        description="Characterized by elements of magic, myth, or the supernatural.",
        subgenres=fantasy_subgenres
    ),
    Genre(
        umbrella="Speculative Fiction",
        name="Science Fiction",
        description="Focuses on advanced technology, space, futuristic societies, or alternate scientific laws.",
        subgenres=sci_fi_subgenres
    ),
    Genre(
        umbrella="Speculative Fiction",
        name="Horror",
        description="Intended to frighten, scare, or disgust the reader by evoking fear and dread.",
        subgenres=horror_subgenres
    ),
    Genre(
        umbrella="Realistic/Commercial Fiction",
        name="Mystery / Crime",
        description="A crime (usually a murder) must be solved by a detective or investigator.",
        subgenres=mystery_subgenres
    ),
    Genre(
        umbrella="Realistic/Commercial Fiction",
        name="Thriller / Suspense",
        description="Defined by a fast pace, high suspense, and a constant sense of danger.",
        subgenres=thriller_subgenres
    ),
    Genre(
        umbrella="Realistic/Commercial Fiction",
        name="Romance",
        description="The primary focus is the development of a love story between the protagonists.",
        subgenres=romance_subgenres
    ),
] + other_fiction_genres