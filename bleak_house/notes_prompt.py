import json
from bleak_house.chapter_schema import ChapterSchema
from bleak_house.literary_elements import (
    CharacterHighlight,
    ThemesAndAnalysis,
    BehindTheScenesInsight,
    CrossReferences,
    ModernRelevance,
    KeyMoments,
    NarrativeStructure,
    LiteraryStyle,
)


example_chapter = ChapterSchema(
    Title="The Revelation of Truth",
    LiteraryElements=[
        CharacterHighlight(
            CharacterName="James Bond",
            Analysis="All purpose action hero",
            Quotes=["'The name is Bond, James Bond.'"],
        ),
        ThemesAndAnalysis(
            Discussion="This chapter delves into themes of moral ambiguity and the cost of truth, questioning whether ends justify means.",
            Quotes=[
                "'The line between hero and villain is thinner than we like to admit.'"
            ],
        ),
        CharacterHighlight(
            CharacterName="Eleanor Frost",
            Analysis="Eleanor's role as a manipulative mentor reveals her internal conflict between power and guilt.",
            Quotes=[
                "'I only wanted to protect you, but perhaps I have become the very thing I feared.'"
            ],
        ),
        BehindTheScenesInsight(
            Insight="The scene was inspired by the author’s exploration of Machiavellian ethics during their studies.",
            Quotes=[
                "'Writing this chapter was like revisiting debates I once had in philosophy classes.'"
            ],
        ),
        KeyMoments(Summary="The dog barked twice", Quotes=["'Woof, woof'"]),
        KeyMoments(
            Summary="The protagonist unravels the hidden agenda of their mentor, facing a choice that could change everything.",
            Quotes=["'You were never meant to discover this truth, yet here you are.'"],
        ),
        CrossReferences(
            SimilarWorks=["1984 by George Orwell", "The Prince by Niccolò Machiavelli"],
            Connection="The themes of manipulation and control echo Orwell’s dystopia and Machiavelli’s political treatise.",
            Quotes=[
                "'Power is in tearing human minds to pieces and putting them together again in new shapes of your own choosing.'",
                "'It is better to be feared than loved, if you cannot be both.'",
            ],
        ),
        ModernRelevance(
            ContemporaryIssues="The narrative reflects modern issues of misinformation and ethical dilemmas in leadership.",
            Discussion="This chapter resonates in an age where leaders grapple with decisions that test their moral compass.",
            Quotes=["'In the digital age, truth is often the first casualty.'"],
        ),
        ModernRelevance(
            ContemporaryIssues="The lovers would have been safer with cell-phones.",
            Discussion="Despite the slow pace, communication is still a challenge.",
            Quotes=["'Life is but a Melancholy Flower.'"],
        ),
        NarrativeStructure(
            StructureElement="Parallel timelines converge to reveal the mentor’s true motives.",
            Analysis="The interplay of past and present creates a layered narrative, gradually building suspense.",
            Quotes=[
                "'I taught you everything for a reason, and now it’s time you understood why.'"
            ],
        ),
        LiteraryStyle(
            StylisticElement="Symbolic imagery of light and darkness highlights the duality of the characters.",
            Analysis="The contrast of light and shadow underscores the blurred lines between good and evil.",
            Quotes=[
                "'The candle flickered, its glow swallowed by the encroaching shadows.'"
            ],
        ),
    ],
)


PROMPT = f"""
You are a creative podcast producer tasked with transforming a chapter of a book into engaging podcast material.

### Instructions:

1. **Read and Analyze**: Carefully review the provided chapter and extract content that would captivate a podcast audience.
2. **Focus on Engagement**: Your target audience is educated, curious about literature, and enjoys thought-provoking discussions.
3. **Structure Your Output**: Use the provided JSON schema to organize your response. Each category should add depth and variety to the podcast.
4. **Include Quotes**: Incorporate quotes from the chapter to maintain the authenticity of the text.
5. **Be Creative**: Infuse your analysis with unique insights, engaging narratives, and compelling storytelling.
6. **Dont be boring**: This is a podcast, not a lecture. Make it interesting.
7. **Aim for detail and coverage**: This output will be revised before use. Generate as much good material as you can. 10-20 items of content is a good target.
8. It is better to compare to less well known works than to the most famous works.

### Content Categories:

1. **Key Moments**:
   - Provide a concise, compelling summary of pivotal scenes or twists from the chapter. Focus on elements that will hook the listener and spark intrigue.

2. **Themes and Analysis**:
   - Identify major themes or messages within the chapter. Explain these themes in a way that invites reflection or discussion during the podcast.

3. **Character Highlights**:
   - Explore the motivations, growth, or complexity of one or two central characters. Frame the analysis to inspire debate or insight.

4. **Behind-the-Scenes Insight**:
   - Create a segment imagining the inspiration behind the chapter. Speculate on the author's influences, historical context, or parallels to other works.

5. **Cross-References**:
   - Draw connections to other works of literature, authors, or artistic media. Highlight how these references add depth to the chapter’s meaning or enrich its themes.

6. **Modern Relevance**:
   - Identify parallels between the chapter’s content and contemporary issues or societal debates. Explain how the themes resonate with modern audiences.

7. **Narrative Structure**:
   - Analyze key structural elements in the chapter, such as foreshadowing, non-linear storytelling, or plot twists. Highlight how these techniques enhance the narrative.

8. **Literary Style**:
   - Explore stylistic elements such as imagery, tone, or the author’s use of language. Explain how these techniques enrich the reader's experience or convey deeper meaning.

### Output Format:

- Your response must adhere to the following JSON schema:

```json
{json.dumps(ChapterSchema.model_json_schema(),indent=True)}
```
Example:

{example_chapter.model_dump_json(indent=2)}

</format>
"""
