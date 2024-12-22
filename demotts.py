from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


text = """
In this episode, we touch on how the Dedlock town house has become a
hub of societal gossip, particularly following Sir Leicester's ailing
health and Lady Dedlock's mysterious absence. The atmosphere is
charged with intrigue, intensified by the emotional toll of Sir
Leicester's quiet suffering, set against the backdrop of an
unforgiving winter storm. Rumors swirl through the community, showing
how personal issues are dissected in public. We shift our focus to
Chesney Wold, where the serene yet melancholic atmosphere highlights
the estate's stagnant state following Lady Dedlock's mysterious death.
Sir Leicester rides towards the mausoleum, burdened by sorrow and
unresolved feuds, revealing the emotional toll of his surroundings.
Fleeting moments of life persist amid the desolation, reflecting on
themes of memory and loss. As we move from the parlors of the Dedlock
household to the dark, winding streets of London, we find ourselves on
a tense and anxiety-filled journey along those mute and ominous paths,
where a search for truth reveals deeper emotional landscapes. Our
protagonist, accompanied by the resolute Inspector Bucket, searches
for her mother amidst the shadows of London. Suspense builds as they
navigate through the night, culminating in a shocking revelation—her
mother is found dead, underscoring the emotional toll of their
mission. In a pivotal encounter, Esther Summerson confronts Mr.
Skimpole about their mutual friend Richard. Her attempts to address
important issues are met with Skimpole's whimsical denials, showcasing
his carefree attitude towards responsibility. This moment highlights
Esther’s internal struggle as she navigates through her feelings for
Mr. Woodcourt, grappling with her own worthiness of love. In a
poignant shift, we follow George the trooper as he travels north to
the iron country, seeking to rekindle his bond with his estranged
brother, Mr. Rouncewell. 
"""

client = OpenAI()
speech_file_path = Path(__file__).parent / "speech.mp3"
response = client.audio.speech.create(
    model="tts-1",
    voice="shimmer",
    input=text,
)
response.write_to_file(speech_file_path)
print(response)