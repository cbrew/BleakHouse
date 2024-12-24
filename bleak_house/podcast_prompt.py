from podcast_schema import Segment, PodcastScript
from literary_elements import (
    KeyMoments,
    ThemesAndAnalysis,
    CharacterHighlight,
    BehindTheScenesInsight,
    CrossReferences,
    ModernRelevance,
    NarrativeStructure,
    LiteraryStyle,
)

example_segment = Segment(
    Title="The Turning Point: Confronting Betrayal",
    LiteraryElements=[
        KeyMoments(
            Summary="The protagonist uncovers the truth about their mentor’s betrayal, setting up a dramatic confrontation.",
            Quotes=["'I trusted you, and this is how you repay me?'"],
        ),
        ThemesAndAnalysis(
            Discussion="This segment focuses on the themes of betrayal and moral ambiguity, examining the protagonist's internal struggle.",
            Quotes=["'Even heroes must walk through shadows to find their light.'"],
        ),
        LiteraryStyle(
            StylisticElement="Symbolic imagery of shattered glass to reflect broken trust.",
            Analysis="The recurring motif of shattered glass underscores the fragility of trust and the consequences of betrayal.",
            Quotes=["'The glass broke, and with it, my illusions of loyalty.'"],
        ),
    ],
)

example_podcast_script = PodcastScript(
    Title="The Complexity of Trust: Betrayal, Redemption, and the Shadows in Between",
    Segments=[
        Segment(
            Title="Opening Scene: A Moment of Truth",
            LiteraryElements=[
                KeyMoments(
                    Summary="Jonas confronts Eleanor in a dimly lit chamber, finally uncovering her manipulative schemes. The tension is palpable as their conflicting truths clash.",
                    Quotes=[
                        "'You were my guiding light, and now I see you were only leading me into the dark.'"
                    ],
                ),
                LiteraryStyle(
                    StylisticElement="The play of light and shadow throughout the scene underscores the moral ambiguity.",
                    Analysis="The flickering candlelight creates an atmosphere of tension, mirroring Jonas’s wavering trust.",
                    Quotes=[
                        "'The shadows swallowed the light, as if echoing Jonas’s collapsing faith.'"
                    ],
                ),
            ],
        ),
        Segment(
            Title="The Theme of Betrayal: How It Shapes Us",
            LiteraryElements=[
                ThemesAndAnalysis(
                    Discussion="Betrayal is more than just an act; it’s the breaking of an unspoken contract. This chapter explores how betrayal forces us to redefine who we are and who we trust.",
                    Quotes=["'A shattered trust is sharper than any sword.'"],
                ),
                CrossReferences(
                    SimilarWorks=[
                        "Berserk by Kentaro Miura (manga)",
                        "The Lord of the Rings by J.R.R. Tolkien",
                        "Circe by Madeline Miller",
                        "Attack on Titan by Hajime Isayama (anime/manga)",
                        "Wuthering Heights by Emily Brontë",
                    ],
                    Connection=(
                        "From the brutal emotional betrayals in 'Berserk' to Tolkien’s exploration of the corruption of power, these works deeply explore betrayal "
                        "and its consequences. 'Circe' reimagines classical myths through betrayal and transformation, while 'Attack on Titan' reveals betrayal "
                        "on both personal and societal scales. In 'Wuthering Heights,' we see how revenge and betrayal spiral across generations."
                    ),
                    Quotes=[
                        "'In this world, is the destiny of mankind controlled by some transcendental entity?' (Berserk)",
                        "'One Ring to rule them all, One Ring to find them.' (Tolkien)",
                        "'Betrayal is the shadow that trails every goddess.' (Circe)",
                        "'This world is cruel. And also very beautiful.' (Attack on Titan)",
                        "'Whatever our souls are made of, his and mine are the same.' (Wuthering Heights)",
                    ],
                ),
            ],
        ),
        Segment(
            Title="Behind the Curtain: The Inspiration",
            LiteraryElements=[
                BehindTheScenesInsight(
                    Insight="The author shared that this chapter drew heavily from personal experiences of navigating betrayal in friendships, alongside their love for high-stakes fantasy worlds like 'Game of Thrones.'",
                    Quotes=[
                        "'This chapter was my way of saying that trust is a fragile thing, easily shattered, yet hard to rebuild.'"
                    ],
                ),
                CrossReferences(
                    SimilarWorks=[
                        "Game of Thrones by George R.R. Martin",
                        "Macbeth by William Shakespeare",
                        "Fullmetal Alchemist by Hiromu Arakawa (manga)",
                    ],
                    Connection=(
                        "'Game of Thrones' provides an intricate web of betrayals, while Shakespeare’s 'Macbeth' explores betrayal in the pursuit of power. "
                        "'Fullmetal Alchemist' delves into themes of sacrifice and the consequences of broken promises, presenting emotional parallels."
                    ),
                    Quotes=[
                        "'When you play the game of thrones, you win or you die.' (Game of Thrones)",
                        "'False face must hide what the false heart doth know.' (Macbeth)",
                        "'A lesson without pain is meaningless. That’s because you can’t gain something without sacrificing something in return.' (Fullmetal Alchemist)",
                    ],
                ),
            ],
        ),
        Segment(
            Title="Character Close-Up: Eleanor and Jonas",
            LiteraryElements=[
                CharacterHighlight(
                    CharacterName="Eleanor Frost",
                    Analysis="Eleanor’s manipulative tactics reveal her belief that the ends justify the means. Her complex moral philosophy makes her a fascinating figure—part villain, part tragic hero.",
                    Quotes=["'I made the choices you couldn’t, for both our sakes.'"],
                ),
                CharacterHighlight(
                    CharacterName="Jonas Reed",
                    Analysis="Jonas starts the chapter as a loyal follower but begins questioning his beliefs. This confrontation marks the start of his transformation into a more self-reliant and morally complex character.",
                    Quotes=[
                        "'If loyalty means losing myself, then I’ll have no part in it.'"
                    ],
                ),
            ],
        ),
        Segment(
            Title="Modern Parallels: Betrayal in Our World",
            LiteraryElements=[
                ModernRelevance(
                    ContemporaryIssues="Jonas’s journey feels incredibly relevant in today’s world of corporate scandals, political betrayals, and public disillusionment. From whistleblowers to broken promises, the story resonates deeply.",
                    Discussion="This chapter raises questions about loyalty and integrity in a world where trust is often broken. It asks us to reflect: when betrayal happens, do we fight to rebuild trust, or walk away?",
                    Quotes=[
                        "'Trust is hard-earned and easily lost—it’s a delicate balance we all navigate daily.'"
                    ],
                )
            ],
        ),
    ],
)

print(example_podcast_script.model_dump_json(indent=4))
