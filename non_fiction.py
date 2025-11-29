from pydantic import BaseModel
from typing import List, Optional

# --------------------------------------------------------------------
# 1. Pydantic Models (Same as fiction.py)
# --------------------------------------------------------------------

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
    time_period: Optional[str] = None
    subject: Optional[str] = None
    tone: Optional[str] = None
    format: Optional[str] = None

class Genre(BaseModel):
    """
    Defines a top-level "Umbrella" Genre, which contains
    a list of its subgenres.
    """
    umbrella: str  # e.g., "Biography & Memoir", "Informational/Academic"
    name: str  # e.g., "History", "Science and Nature"
    description: str
    subgenres: List[Subgenre]

# --------------------------------------------------------------------
# 2. Subgenre Definitions
# --------------------------------------------------------------------

# --- 1. BIOGRAPHY AND MEMOIR ---
biography_subgenres = [
    Subgenre(
        name="Autobiography",
        description="Written by the subject themselves, focusing on their entire life.",
        subject="Author",
        time_period="Full Life"
    ),
    Subgenre(
        name="Memoir",
        description="Written by the subject, focusing on a specific theme, period, or aspect of their life.",
        subject="Author",
        themes=["Specific Life Event"]
    ),
    Subgenre(
        name="Biography",
        description="Written by someone other than the subject.",
        subject="Other Person"
    ),
    Subgenre(
        name="Collective Biography",
        description="Focuses on the lives of a group of people.",
        subject="Group of People"
    ),
]

# --- 2. HISTORY ---
history_subgenres = [
    Subgenre(
        name="Military History",
        description="Focuses on conflicts, battles, and military strategy.",
        time_period="Historical",
        themes=["War/Conflict"]
    ),
    Subgenre(
        name="Social History",
        description="Focuses on the lives of everyday people, culture, and societal trends.",
        themes=["Culture/Society"]
    ),
    Subgenre(
        name="Political History",
        description="Focuses on governments, leaders, policies, and political movements.",
        themes=["Politics/Government"]
    ),
    Subgenre(
        name="Archaeology",
        description="Focuses on the study of human history and prehistory through excavation and analysis.",
        themes=["Ancient History"]
    ),
]

# --- 3. SCIENCE AND NATURE ---
science_subgenres = [
    Subgenre(
        name="Popular Science",
        description="Explains complex scientific ideas to a general audience.",
        themes=["General Audience"]
    ),
    Subgenre(
        name="Natural History",
        description="Focuses on the observation of organisms and ecosystems.",
        setting="Rural/Nature"
    ),
    Subgenre(
        name="Physics/Astronomy",
        description="Focuses on the physical universe, from subatomic particles to galaxies.",
        themes=["Theoretical Concepts"]
    ),
    Subgenre(
        name="Technology & Computing",
        description="Focuses on practical and theoretical aspects of modern tech and coding.",
        themes=["Technical Skill"]
    ),
]

# --- 4. SELF-HELP AND PERSONAL DEVELOPMENT ---
self_help_subgenres = [
    Subgenre(
        name="Productivity/Business",
        description="Focuses on improving efficiency, management, and financial success.",
        themes=["Career/Finance"]
    ),
    Subgenre(
        name="Mental Health/Wellness",
        description="Focuses on improving psychological well-being, mindfulness, and habits.",
        themes=["Mental Health"]
    ),
    Subgenre(
        name="Motivational",
        description="Focuses on inspirational stories or philosophies to encourage action.",
        tone="Inspirational"
    ),
    Subgenre(
        name="Relationship Advice",
        description="Focuses on guidance for dating, marriage, or family dynamics.",
        themes=["Relationships"]
    ),
]

# --- 5. INSTRUCTIONAL / HOW-TO ---
instructional_subgenres = [
    Subgenre(
        name="Cookbooks",
        description="Provides recipes and techniques related to food preparation.",
        themes=["Cuisine/Diet"]
    ),
    Subgenre(
        name="DIY/Crafts",
        description="Provides instructions for creating objects, home repair, or specialized crafts.",
        themes=["Home Improvement"]
    ),
    Subgenre(
        name="Fitness/Exercise",
        description="Focuses on workout routines, training, and physical health.",
        themes=["Physical Fitness"]
    ),
    Subgenre(
        name="Travel Guides",
        description="Provides destination-specific information.",
        setting="Specific Location"
    ),
]

# --- 6. JOURNALISM AND TRUE CRIME ---
journalism_subgenres = [
    Subgenre(
        name="Investigative Journalism",
        description="Deep research and analysis into a specific issue or controversy.",
        themes=["Current Events/Politics"]
    ),
    Subgenre(
        name="Creative Non-Fiction",
        description="Uses literary styles (like dialogue and stream-of-consciousness) to report facts.",
        tone="Literary"
    ),
    Subgenre(
        name="True Crime",
        description="Detailed accounts of real crimes, focusing on the investigation and legal process.",
        themes=["Crime/Legal"]
    ),
    Subgenre(
        name="Essays",
        description="Short pieces of writing that explore a subject or argue a specific point of view.",
        format="Collection of Short Pieces"
    ),
]

# --- 7. RELIGIOUS AND PHILOSOPHICAL ---
philosophy_subgenres = [
    Subgenre(
        name="Theology",
        description="The study of the nature of God and religious belief.",
        themes=["Religious Doctrine"]
    ),
    Subgenre(
        name="Philosophy",
        description="Exploration of fundamental truths about existence, knowledge, and values.",
        themes=["Abstract Thought"]
    ),
    Subgenre(
        name="Comparative Religion",
        description="Analyzes the similarities and differences between world religions.",
        themes=["Multiple Belief Systems"]
    ),
]

# --------------------------------------------------------------------
# 3. The Final Compiled List
# --------------------------------------------------------------------

NON_FICTION_GENRES: List[Genre] = [
    Genre(
        umbrella="Biography & Memoir",
        name="Biography & Memoir",
        description="The life story of a real person (or group).",
        subgenres=biography_subgenres
    ),
    Genre(
        umbrella="Informational/Academic",
        name="History",
        description="Focuses on past events, timelines, and analysis.",
        subgenres=history_subgenres
    ),
    Genre(
        umbrella="Informational/Academic",
        name="Science and Nature",
        description="Focuses on the natural world, scientific discovery, and technology.",
        subgenres=science_subgenres
    ),
    Genre(
        umbrella="Informational/Academic",
        name="Self-Help",
        description="Intended to instruct readers on how to solve personal problems or improve their lives.",
        subgenres=self_help_subgenres
    ),
    Genre(
        umbrella="Practical/Instructional",
        name="Instructional / How-To",
        description="Guiding the reader through a specific activity or skill.",
        subgenres=instructional_subgenres
    ),
    Genre(
        umbrella="Narrative/Creative",
        name="Journalism & True Crime",
        description="Using fictional techniques (storytelling) to convey factual events.",
        subgenres=journalism_subgenres
    ),
    Genre(
        umbrella="Informational/Academic",
        name="Religious & Philosophical",
        description="Focuses on beliefs, existential questions, and spiritual practices.",
        subgenres=philosophy_subgenres
    ),
]