import json
import re
from string import Template
from pingpong.scripts.qualtrics.schemas import ExamJSON, AirtableClass, ExamQuestion


def escape_latex_within_span(text):
    text = text.replace(r"''(", r"temp_prime_prime(")
    text = text.replace(r"'(", r"temp_prime(")

    text = text.replace('\\"', '"')
    text = text.replace("'", '"')

    text = text.replace(r"temp_prime_prime(", r"''(")
    text = text.replace(r"temp_prime(", r"'(")
    pattern = r"(<span class=\"katex\">)(.*?)(</span>)"

    def escape(match):
        content = match.group(2)
        print("SPAN CONTENT:", content)
        # Remove LaTeX delimiters
        # Preserve escaped dollar signs
        content = content.replace(r"\$", r"\dollars")
        # Remove LaTeX delimiters
        content = content.replace("$", "")
        content = content.replace(r"\dollars", r"\$")  # Restore escaped dollar signs
        content = content.replace("\\(", "")
        content = content.replace("\\)", "")
        content = content.replace("\\[", "")
        content = content.replace("\\]", "")
        # Remove newline characters
        content = content.replace("\n", "")
        # Fix special characters
        content = content.replace("&gt;", " \gt ")
        content = content.replace("&lt;", " \lt ")
        content = content.replace("=>", "=\textgreater{}")
        content = content.replace(r"\langlet ", r"\textless{}")
        content = content.replace(r"\langlet", r"\textless{}")
        content = content.replace(r"\ranglet ", r"\textgreater{}")
        content = content.replace(r"\ranglet", r"\textgreater{}")
        print("AFTER FIX:", content)
        content = content.replace("geom_", "geom\_")
        content = content.replace(r"\vec ", r"\overrightarrow")
        content = content.replace("<", " \lt ")
        content = content.replace(">", " \gt ")
        content = content.replace("u2264", " leq ")
        content = content.replace("u2265", " geq ")
        # Escape special characters
        content = re.sub(r"\\", r"\\\\", content)
        content = re.sub(r'"', r'\\"', content)
        print("ESCAPED CONTENT:", content)
        if "{array}" in content:
            return rf"<br><br><span class=\"katex\" style=\"font-size: 0.9em;white-space: nowrap;\">{content}{match.group(3)}<br><br>"
        else:
            return rf"<span class=\"katex\" style=\"font-size: 0.9em;white-space: nowrap;\">{content}{match.group(3)}"

    text = re.sub(pattern, escape, text, flags=re.DOTALL)
    return text


def escape_non_span(text):
    text = text.replace("\n", "<br>")
    text = text.replace("· ", "<br>&middot; ")
    text = text.replace("\%", "&#37;")
    text = text.replace("\\u2265", "&ge;")
    text = text.replace("\u2265", "&ge;")
    text = text.replace("\\u2264", "&le;")
    text = text.replace("\u2264", "&le;")
    text = re.sub(r" {2,}", lambda m: "&nbsp;" * len(m.group(0)), text)
    text = re.sub(r'(?<!\\)"', r'\\"', text)
    return text


def escape_non_span_options(text):
    text = text.replace("\n", "<br>")
    text = text.replace("· ", "<br>&middot; ")
    text = text.replace("\%", "&#37;")
    text = text.replace("\\u00026le", "&le;")
    text = text.replace("\\u2265", "&ge;")
    text = text.replace("\u2265", "&ge;")
    text = text.replace("\\u2264", "&le;")
    text = text.replace("\u2264", "&le;")
    text = re.sub(r" {2,}", lambda m: "&nbsp;" * len(m.group(0)), text)
    return text


def escape_latex_within_span_options(text):
    text = text.replace(r"''(", r"temp_prime_prime(")
    text = text.replace(r"'(", r"temp_prime(")

    text = text.replace('\\"', '"')
    text = text.replace("'", '"')

    text = text.replace(r"temp_prime_prime(", r"''(")
    text = text.replace(r"temp_prime(", r"'(")
    pattern = r"(<span class=\"katex\">)(.*?)(</span>)"

    def escape(match):
        content = match.group(2)
        print("SPAN CONTENT:", content)
        # Preserve escaped dollar signs
        content = content.replace(r"\$", r"\dollars")
        # Remove LaTeX delimiters
        content = content.replace("$", "")
        content = content.replace(r"\dollars", r"\$")  # Restore escaped dollar signs
        content = content.replace("\\(", "")
        content = content.replace("\\)", "")
        content = content.replace("\\[", "")
        content = content.replace("\\]", "")
        # Remove newline characters
        content = content.replace("\n", "")
        # Fix special characters
        content = content.replace("=>", "=\\textgreater{}")
        content = content.replace("\\langlet ", "\\textless{}")
        content = content.replace("\\langlet", "\\textless{}")
        content = content.replace("\\ranglet ", "\\textgreater{}")
        content = content.replace("\\ranglet", "\\textgreater{}")
        content = content.replace("geom_", "geom\\_")
        content = content.replace("&gt;", " \\gt ")
        content = content.replace("&lt;", " \\lt ")
        content = content.replace("<", " \\lt ")
        content = content.replace(">", " \\gt ")
        content = content.replace("u2264", " leq ")
        content = content.replace("u2265", " geq ")
        print("ESCAPED CONTENT:", content)
        return f'<span class="katex" style="font-size: 0.9em;white-space: nowrap;">{content}{match.group(3)}'

    text = re.sub(pattern, escape, text, flags=re.DOTALL)
    return text


def escape_text(text, question_number):
    if not text.startswith("Question") and not text.endswith("<b>Question"):
        text = "<b>Question " + str(question_number) + "/10:</b><br>" + text
    pattern = r'(<span\s+class=\\?["\']?katex\\?["\']?>.*?</span>)'
    segments = re.split(pattern, text, flags=re.DOTALL)

    for i, seg in enumerate(segments):
        if re.fullmatch(pattern, seg, flags=re.DOTALL):
            print("SPAN", seg)
            segments[i] = escape_latex_within_span(seg)
        else:
            print("NOT SPAN", seg)
            segments[i] = escape_non_span(seg)

    return "".join(segments)


def escape_option_text(text):
    pattern = r'(<span\s+class=\\?["\']?katex\\?["\']?>.*?</span>)'
    segments = re.split(pattern, text)

    for i, seg in enumerate(segments):
        if re.fullmatch(pattern, seg):
            print("SPAN", seg)
            segments[i] = escape_latex_within_span_options(seg)
        else:
            print("NOT SPAN", seg)
            segments[i] = escape_non_span_options(seg)

    return "".join(segments)


def qsf_choices(options: list[str]) -> str:
    option_dict = {}
    for i, option in enumerate(options):
        option_dict[str(i + 1)] = {"Display": escape_option_text(option)}
    return json.dumps(option_dict)


def qsf_choice_order(options: list[str]) -> str:
    return json.dumps([str(i) for i in range(1, len(options) + 1)])


def qsf_recoded_values(options: list[str]) -> str:
    return json.dumps({str(i): str(i) for i in range(1, len(options) + 1)})


def correct_choice_id(question: ExamQuestion) -> str:
    """Return Qualtrics choice ID (1-indexed) for the provided correct answer."""
    try:
        return str(question.options.index(question.answer) + 1)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ValueError(
            f"Answer '{question.answer}' not found in options for question '{question.question}'"
        ) from exc


def generate_qsf(exam: ExamJSON, class_: AirtableClass) -> str:
    return EXAM_QSF_TEMPLATE.substitute(
        CourseName=class_.name,
        CourseAirtableID=class_.id,
        PingPongClassID=class_.pingpong_class_id[0] if class_.pingpong_class_id else -1,
        CourseRandomization=class_.randomization,
        Footer=KATEX_FOOTER if exam.uses_latex else NON_KATEX_FOOTER,
        A1QuestionText=escape_text(exam.questions[0].question, 1),
        A1Choices=qsf_choices(exam.questions[0].options),
        A1ChoiceOrder=qsf_choice_order(exam.questions[0].options),
        A1RecodeValues=qsf_recoded_values(exam.questions[0].options),
        A1JavaScript=f'"{KATEX_QS_JS}"' if exam.questions[0].uses_latex else '""',
        A1CorrectChoiceID=correct_choice_id(exam.questions[0]),
        A2QuestionText=escape_text(exam.questions[1].question, 2),
        A2Choices=qsf_choices(exam.questions[1].options),
        A2ChoiceOrder=qsf_choice_order(exam.questions[1].options),
        A2RecodeValues=qsf_recoded_values(exam.questions[1].options),
        A2JavaScript=f'"{KATEX_QS_JS}"' if exam.questions[1].uses_latex else '""',
        A2CorrectChoiceID=correct_choice_id(exam.questions[1]),
        A3QuestionText=escape_text(exam.questions[2].question, 3),
        A3Choices=qsf_choices(exam.questions[2].options),
        A3ChoiceOrder=qsf_choice_order(exam.questions[2].options),
        A3RecodeValues=qsf_recoded_values(exam.questions[2].options),
        A3JavaScript=f'"{KATEX_QS_JS}"' if exam.questions[2].uses_latex else '""',
        A3CorrectChoiceID=correct_choice_id(exam.questions[2]),
        A4QuestionText=escape_text(exam.questions[3].question, 4),
        A4Choices=qsf_choices(exam.questions[3].options),
        A4ChoiceOrder=qsf_choice_order(exam.questions[3].options),
        A4RecodeValues=qsf_recoded_values(exam.questions[3].options),
        A4JavaScript=f'"{KATEX_QS_JS}"' if exam.questions[3].uses_latex else '""',
        A4CorrectChoiceID=correct_choice_id(exam.questions[3]),
        A5QuestionText=escape_text(exam.questions[4].question, 5),
        A5Choices=qsf_choices(exam.questions[4].options),
        A5ChoiceOrder=qsf_choice_order(exam.questions[4].options),
        A5RecodeValues=qsf_recoded_values(exam.questions[4].options),
        A5JavaScript=f'"{KATEX_QS_JS}"' if exam.questions[4].uses_latex else '""',
        A5CorrectChoiceID=correct_choice_id(exam.questions[4]),
        A6QuestionText=escape_text(exam.questions[5].question, 6),
        A6Choices=qsf_choices(exam.questions[5].options),
        A6ChoiceOrder=qsf_choice_order(exam.questions[5].options),
        A6RecodeValues=qsf_recoded_values(exam.questions[5].options),
        A6JavaScript=f'"{KATEX_QS_JS}"' if exam.questions[5].uses_latex else '""',
        A6CorrectChoiceID=correct_choice_id(exam.questions[5]),
        A7QuestionText=escape_text(exam.questions[6].question, 7),
        A7Choices=qsf_choices(exam.questions[6].options),
        A7ChoiceOrder=qsf_choice_order(exam.questions[6].options),
        A7RecodeValues=qsf_recoded_values(exam.questions[6].options),
        A7JavaScript=f'"{KATEX_QS_JS}"' if exam.questions[6].uses_latex else '""',
        A7CorrectChoiceID=correct_choice_id(exam.questions[6]),
        A8QuestionText=escape_text(exam.questions[7].question, 8),
        A8Choices=qsf_choices(exam.questions[7].options),
        A8ChoiceOrder=qsf_choice_order(exam.questions[7].options),
        A8RecodeValues=qsf_recoded_values(exam.questions[7].options),
        A8JavaScript=f'"{KATEX_QS_JS}"' if exam.questions[7].uses_latex else '""',
        A8CorrectChoiceID=correct_choice_id(exam.questions[7]),
        A9QuestionText=escape_text(exam.questions[8].question, 9),
        A9Choices=qsf_choices(exam.questions[8].options),
        A9ChoiceOrder=qsf_choice_order(exam.questions[8].options),
        A9RecodeValues=qsf_recoded_values(exam.questions[8].options),
        A9JavaScript=f'"{KATEX_QS_JS}"' if exam.questions[8].uses_latex else '""',
        A9CorrectChoiceID=correct_choice_id(exam.questions[8]),
        A10QuestionText=escape_text(exam.questions[9].question, 10),
        A10Choices=qsf_choices(exam.questions[9].options),
        A10ChoiceOrder=qsf_choice_order(exam.questions[9].options),
        A10RecodeValues=qsf_recoded_values(exam.questions[9].options),
        A10JavaScript=f'"{KATEX_QS_JS}"' if exam.questions[9].uses_latex else '""',
        A10CorrectChoiceID=correct_choice_id(exam.questions[9]),
        TestJavaScript=f'"{KATEX_QS_JS}"'
        if any(q.uses_latex for q in exam.questions)
        else '""',
    )


KATEX_QS_JS = r"Qualtrics.SurveyEngine.addOnload(function()\n{\n\tjQuery(\".katex\").each(function() {\n\t\tlet htmlText = this.innerHTML;\n\t\thtmlText = htmlText.replace(\/&amp;\/g, '&');\n\t\tkatex.render(htmlText, this, { throwOnError: false });\n\t});\n});\n\nQualtrics.SurveyEngine.addOnReady(function()\n{\n\t/*Place your JavaScript here to run when the page is fully displayed*/\n\n});\n\nQualtrics.SurveyEngine.addOnUnload(function()\n{\n\t/*Place your JavaScript here to run when the page is unloaded*/\n\n});"

NON_KATEX_FOOTER = r"<script src=\"https://ajax.googleapis.com/ajax/libs/jquery/3.7.1/jquery.min.js\"></script>"

KATEX_FOOTER = r"<script src=\"https://ajax.googleapis.com/ajax/libs/jquery/3.7.1/jquery.min.js\"></script>\n<link crossorigin=\"anonymous\" href=\"https://cdn.jsdelivr.net/npm/katex@0.16.21/dist/katex.min.css\" integrity=\"sha384-zh0CIslj+VczCZtlzBcjt5ppRcsAmDnRem7ESsYwWwg3m/OaJ2l4x7YBZl9Kxxib\" rel=\"stylesheet\" /><script defer src=\"https://cdn.jsdelivr.net/npm/katex@0.16.21/dist/katex.min.js\" integrity=\"sha384-Rma6DA2IPUwhNxmrB/7S3Tno0YY7sFu9WSYMCuulLhIqYSGZ2gKCJWIqhBWqMQfh\" crossorigin=\"anonymous\"></script>"

EXAM_QSF_TEMPLATE = Template(r"""
{
  "SurveyEntry": {
    "SurveyID": "SV_eP5ggSR1YMcI2HA",
    "SurveyName": "$CourseName ($CourseAirtableID)",
    "SurveyDescription": null,
    "SurveyOwnerID": "UR_bQHormGseyEZkzz",
    "SurveyBrandID": "harvard",
    "DivisionID": "DV_bdu3uP2WTYThpOY",
    "SurveyLanguage": "EN",
    "SurveyActiveResponseSet": "RS_8ukqoqmF9idDUai",
    "SurveyStatus": "Active",
    "SurveyStartDate": "2025-03-13 22:15:26",
    "SurveyExpirationDate": "0000-00-00 00:00:00",
    "SurveyCreationDate": "2025-03-13 22:03:07",
    "CreatorID": "UR_bQHormGseyEZkzz",
    "LastModified": "2025-03-27 10:16:47",
    "LastAccessed": "0000-00-00 00:00:00",
    "LastActivated": "2025-03-13 22:15:26",
    "Deleted": null
  },
  "SurveyElements": [
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "BL",
      "PrimaryAttribute": "Survey Blocks",
      "SecondaryAttribute": null,
      "TertiaryAttribute": null,
      "Payload": {
        "0": {
          "Type": "Default",
          "Description": "Starters",
          "ID": "BL_3xyVR7mBcg6zsy2",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID8"
            },
            {
              "Type": "Question",
              "QuestionID": "QID2"
            },
            {
              "Type": "Question",
              "QuestionID": "QID3"
            },
            {
              "Type": "Question",
              "QuestionID": "QID73"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "1": {
          "Type": "Trash",
          "Description": "Trash / Unused Questions",
          "ID": "BL_eRSnjT50eksEcZ0",
          "BlockElements": []
        },
        "3": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Affective Questions",
          "ID": "BL_2gwh3Zh9Q3Nsn3g",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID35"
            },
            {
              "Type": "Question",
              "QuestionID": "QID62"
            },
            {
              "Type": "Question",
              "QuestionID": "QID63"
            },
            {
              "Type": "Question",
              "QuestionID": "QID68"
            },
            {
              "Type": "Question",
              "QuestionID": "QID64"
            },
            {
              "Type": "Question",
              "QuestionID": "QID65"
            },
            {
              "Type": "Question",
              "QuestionID": "QID66"
            },
            {
              "Type": "Question",
              "QuestionID": "QID69"
            },
            {
              "Type": "Question",
              "QuestionID": "QID70"
            },
            {
              "Type": "Question",
              "QuestionID": "QID72"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "5": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Assessment / Assignment P2",
          "ID": "BL_eXTDb32KHtQmrCC",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID61"
            },
            {
              "Type": "Question",
              "QuestionID": "QID10"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "6": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Assessment / Assignment P3",
          "ID": "BL_4NPsuuYPXBL98RU",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID11"
            },
            {
              "Type": "Question",
              "QuestionID": "QID12"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "7": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Assessment / Assignment P4",
          "ID": "BL_9QwB36qPFHdIDBk",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID13"
            },
            {
              "Type": "Question",
              "QuestionID": "QID14"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "8": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Assessment / Assignment P9",
          "ID": "BL_eDp7soVERGKBjPo",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID23"
            },
            {
              "Type": "Question",
              "QuestionID": "QID24"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "9": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Assessment / Assignment P5",
          "ID": "BL_9Zit4slSWS66C3Q",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID15"
            },
            {
              "Type": "Question",
              "QuestionID": "QID16"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "10": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Assessment / Assignment P6",
          "ID": "BL_2sDajWT9TUHCpdI",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID17"
            },
            {
              "Type": "Question",
              "QuestionID": "QID18"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "11": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Assessment / Assignment P7",
          "ID": "BL_5zM85wHhtCUK75k",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID19"
            },
            {
              "Type": "Question",
              "QuestionID": "QID20"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "12": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Assessment / Assignment P8",
          "ID": "BL_6tept7fmRvGOKq2",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID25"
            },
            {
              "Type": "Question",
              "QuestionID": "QID26"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "13": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Assessment / Assignment P1",
          "ID": "BL_b9Gvnb6ouT0YN3U",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID28"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "PreviousButton": "",
            "previousButtonMID": "",
            "NextButton": "Start assignment",
            "nextButtonMID": "",
            "previousButtonLibraryID": "",
            "nextButtonLibraryID": "",
            "BlockVisibility": "Expanded"
          }
        },
        "16": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Verify_Primary",
          "ID": "BL_3XcOLSMVJpP6fHM",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID47"
            },
            {
              "Type": "Question",
              "QuestionID": "QID48"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "17": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Verify_Resend",
          "ID": "BL_br40aFNTwf5ttB4",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID49"
            },
            {
              "Type": "Question",
              "QuestionID": "QID50"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "18": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Verify_New",
          "ID": "BL_8G3NLOlCdaTUwGq",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID51"
            },
            {
              "Type": "Question",
              "QuestionID": "QID52"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "19": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Assessment / Assignment P10",
          "ID": "BL_4HkRdnR2XTOq5tI",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID53"
            },
            {
              "Type": "Question",
              "QuestionID": "QID54"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "20": {
          "Type": "Standard",
          "SubType": "",
          "Description": "Assessment / Assignment P11",
          "ID": "BL_easvL0yqaT6vGjI",
          "BlockElements": [
            {
              "Type": "Question",
              "QuestionID": "QID56"
            },
            {
              "Type": "Question",
              "QuestionID": "QID55"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        },
        "21":{
          "Type":"Standard",
          "SubType":"",
          "Description":"Review Block",
          "ID":"BL_d3RPBjSzEtPopbU",
          "BlockElements":[
            {
                "Type":"Question",
                "QuestionID":"QID76"
            },
            {
                "Type":"Question",
                "QuestionID":"QID77"
            },
            {
                "Type":"Question",
                "QuestionID":"QID79"
            },
            {
                "Type":"Question",
                "QuestionID":"QID75"
            },
            {
                "Type":"Question",
                "QuestionID":"QID80"
            },
            {
                "Type":"Question",
                "QuestionID":"QID81"
            },
            {
                "Type":"Question",
                "QuestionID":"QID82"
            },
            {
                "Type":"Question",
                "QuestionID":"QID83"
            },
            {
                "Type":"Question",
                "QuestionID":"QID84"
            },
            {
                "Type":"Question",
                "QuestionID":"QID85"
            }
          ],
          "Options": {
            "BlockLocking": "false",
            "RandomizeQuestions": "false",
            "BlockVisibility": "Expanded"
          }
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "FL",
      "PrimaryAttribute": "Survey Flow",
      "SecondaryAttribute": null,
      "TertiaryAttribute": null,
      "Payload": {
        "Type": "Root",
        "FlowID": "FL_1",
        "Flow": [
          {
            "Type": "EmbeddedData",
            "FlowID": "FL_52",
            "EmbeddedData": [
              {
                "Description": "pp_class_id",
                "Type": "Custom",
                "Field": "pp_class_id",
                "VariableType": "String",
                "DataVisibility": [],
                "AnalyzeText": false,
                "Value": "$PingPongClassID"
              },
              {
                "Description": "pp_class_name",
                "Type": "Custom",
                "Field": "pp_class_name",
                "VariableType": "String",
                "DataVisibility": [],
                "AnalyzeText": false,
                "Value": "$CourseName"
              },
              {
                "Description": "pp_randomization",
                "Type": "Custom",
                "Field": "pp_randomization",
                "VariableType": "String",
                "DataVisibility": [],
                "AnalyzeText": false,
                "Value": "$CourseRandomization"
              },
              {
                "Description": "pp_airtable_class_RID",
                "Type": "Custom",
                "Field": "pp_airtable_class_RID",
                "VariableType": "String",
                "DataVisibility": [],
                "AnalyzeText": false,
                "Value": "$CourseAirtableID"
              },
              {
                "Description": "__js_airtable_student_RID",
                "Type": "Recipient",
                "Field": "__js_airtable_student_RID",
                "VariableType": "String",
                "DataVisibility": [],
                "AnalyzeText": false
              },
              {
                "Description": "__js_failed_attempts_email",
                "Type": "Custom",
                "Field": "__js_failed_attempts_email",
                "VariableType": "String",
                "DataVisibility": [],
                "AnalyzeText": false,
                "Value": "0"
              },
              {
                "Description":"__js_airtable_bypass_survey",
                "Type":"Recipient",
                "Field":"__js_airtable_bypass_survey",
                "VariableType":"String",
                "DataVisibility":[

                ],
                "AnalyzeText":false
              }
            ]
          },
          {
            "Type":"Branch",
            "FlowID":"FL_61",
            "Description":"New Branch",
            "BranchLogic":{
                "0":{
                  "0":{
                      "LogicType":"EmbeddedField",
                      "LeftOperand":"__js_airtable_bypass_survey",
                      "Operator":"Contains",
                      "RightOperand":"@rct@",
                      "_HiddenExpression":false,
                      "Type":"Expression",
                      "Description":"<span class=\"ConjDesc\">If<\/span> <span class=\"LeftOpDesc\">__js_airtable_bypass_survey<\/span> <span class=\"OpDesc\">Contains<\/span> <span class=\"RightOpDesc\"> @rct@ <\/span>"
                  },
                  "Type":"If"
                },
                "Type":"BooleanExpression"
            },
            "Flow":[
                {
                  "Type":"Block",
                  "ID":"BL_d3RPBjSzEtPopbU",
                  "FlowID":"FL_62",
                  "Autofill":[

                  ]
                },
                {
                  "Type":"EndSurvey",
                  "FlowID":"FL_63",
                  "EndingType":"Advanced",
                  "Options":{
                      "Advanced":"true",
                      "SurveyTermination":"DisplayMessage",
                      "EOSMessageLibrary":"UR_bQHormGseyEZkzz",
                      "EOSMessage":"MS_d4CsfOr3LWsJfwy",
                      "CountQuotas":"No",
                      "AnonymizeResponse":"Yes",
                      "EmailThankYou":"",
                      "IgnoreResponse":"Yes",
                      "ResponseFlag":"Screened"
                  }
                }
            ]
          },
          {
            "Type": "Block",
            "ID": "BL_3xyVR7mBcg6zsy2",
            "FlowID": "FL_2",
            "Autofill": []
          },
          {
            "Type":"Branch",
            "FlowID":"FL_55",
            "Description":"New Branch",
            "BranchLogic":{
                "0":{
                  "0":{
                      "LogicType":"Question",
                      "QuestionID":"QID3",
                      "QuestionIsInLoop":"no",
                      "ChoiceLocator":"q:\/\/QID3\/ChoiceTextEntryValue",
                      "Operator":"Contains",
                      "QuestionIDFromLocator":"QID3",
                      "LeftOperand":"q:\/\/QID3\/ChoiceTextEntryValue",
                      "RightOperand":"@RCT@",
                      "IgnoreCase":1,
                      "Type":"Expression",
                      "Description":"<span class=\"ConjDesc\">If<\/span> <span class=\"QuestionDesc\">Academic Email Use the same email you used to complete the assignment earlier this semester, even...<\/span> <span class=\"LeftOpDesc\">Text Response<\/span> <span class=\"OpDesc\">Contains<\/span> <span class=\"RightOpDesc\"> @RCT@ <\/span>"
                  },
                  "Type":"If"
                },
                "Type":"BooleanExpression"
            },
            "Flow":[
                {
                  "Type":"Standard",
                  "ID":"BL_d3RPBjSzEtPopbU",
                  "FlowID":"FL_58",
                  "Autofill":[

                  ]
                },
                {
                  "Type":"EndSurvey",
                  "FlowID":"FL_56",
                  "EndingType":"Advanced",
                  "Options":{
                      "Advanced":"true",
                      "SurveyTermination":"DisplayMessage",
                      "EOSMessageLibrary":"UR_bQHormGseyEZkzz",
                      "EOSMessage":"MS_d4CsfOr3LWsJfwy",
                      "CountQuotas":"No",
                      "AnonymizeResponse":"Yes",
                      "EmailThankYou":"",
                      "IgnoreResponse":"Yes",
                      "ResponseFlag":"Screened"
                  }
                }
            ]
          },
          {
            "Type": "Branch",
            "FlowID": "FL_54",
            "Description": "New Branch",
            "BranchLogic": {
              "0": {
                "0": {
                  "LogicType": "Question",
                  "QuestionID": "QID3",
                  "QuestionIsInLoop": "no",
                  "ChoiceLocator": "q://QID3/ChoiceTextEntryValue",
                  "Operator": "DoesNotContain",
                  "QuestionIDFromLocator": "QID3",
                  "LeftOperand": "q://QID3/ChoiceTextEntryValue",
                  "RightOperand": "@RCT@",
                  "IgnoreCase": 1,
                  "Type": "Expression",
                  "Description": "<span class=\"ConjDesc\">If</span> <span class=\"QuestionDesc\">Academic Email Use the same email you used to complete the assignment earlier this semester, even...</span> <span class=\"LeftOpDesc\">Text Response</span> <span class=\"OpDesc\">Does Not Contain</span> <span class=\"RightOpDesc\"> @RCT@ </span>"
                },
                "Type": "If"
              },
              "Type": "BooleanExpression"
            },
            "Flow": [
              {
                "Type": "EmbeddedData",
                "FlowID": "FL_35",
                "EmbeddedData": [
                  {
                    "Description": "primary_email_verification",
                    "Type": "Custom",
                    "Field": "primary_email_verification",
                    "VariableType": "String",
                    "DataVisibility": [],
                    "AnalyzeText": false,
                    "Value": "$${rand://int/1000:9999}"
                  }
                ]
              },
              {
                "Type": "WebService",
                "FlowID": "FL_34",
                "URL": "https://hooks.airtable.com/workflows/v1/genericWebhook/appVTPUUDF3ADmhzt/wflXjGYq8j3n31dRg/wtrW3iL7AWJdE34uY",
                "Method": "POST",
                "RequestParams": [],
                "EditBodyParams": [
                  {
                    "key": "code",
                    "value": "$${e://Field/primary_email_verification}"
                  },
                  {
                    "key": "email",
                    "value": "$${q://QID3/ChoiceTextEntryValue}"
                  }
                ],
                "Body": {
                  "code": "$${e://Field/primary_email_verification}",
                  "email": "$${q://QID3/ChoiceTextEntryValue}"
                },
                "ContentType": "application/json",
                "Headers": [],
                "ResponseMap": [],
                "FireAndForget": false,
                "SchemaVersion": 0,
                "StringifyValues": true
              },
              {
                "Type": "Standard",
                "ID": "BL_3XcOLSMVJpP6fHM",
                "FlowID": "FL_32",
                "Autofill": []
              },
              {
                "Type": "Branch",
                "FlowID": "FL_38",
                "Description": "New Branch",
                "BranchLogic": {
                  "0": {
                    "0": {
                      "LogicType": "Question",
                      "QuestionID": "QID48",
                      "QuestionIsInLoop": "no",
                      "ChoiceLocator": "q://QID48/SelectableChoice/1",
                      "Operator": "Selected",
                      "QuestionIDFromLocator": "QID48",
                      "LeftOperand": "q://QID48/SelectableChoice/1",
                      "Type": "Expression",
                      "Description": "<span class=\"ConjDesc\">If</span> <span class=\"QuestionDesc\">Having issues receiving the code?</span> <span class=\"LeftOpDesc\">Check this box to resend the code.</span> <span class=\"OpDesc\">Is Selected</span> "
                    },
                    "Type": "If"
                  },
                  "Type": "BooleanExpression"
                },
                "Flow": [
                  {
                    "Type": "WebService",
                    "FlowID": "FL_47",
                    "URL": "https://hooks.airtable.com/workflows/v1/genericWebhook/appVTPUUDF3ADmhzt/wflXjGYq8j3n31dRg/wtrW3iL7AWJdE34uY",
                    "Method": "POST",
                    "RequestParams": [],
                    "EditBodyParams": [
                      {
                        "key": "code",
                        "value": "$${e://Field/primary_email_verification}"
                      },
                      {
                        "key": "email",
                        "value": "$${q://QID3/ChoiceTextEntryValue}"
                      }
                    ],
                    "Body": {
                      "code": "$${e://Field/primary_email_verification}",
                      "email": "$${q://QID3/ChoiceTextEntryValue}"
                    },
                    "ContentType": "application/json",
                    "Headers": [],
                    "ResponseMap": [],
                    "FireAndForget": false,
                    "SchemaVersion": 0,
                    "StringifyValues": true
                  },
                  {
                    "Type": "Standard",
                    "ID": "BL_br40aFNTwf5ttB4",
                    "FlowID": "FL_36",
                    "Autofill": []
                  },
                  {
                    "Type": "Branch",
                    "FlowID": "FL_43",
                    "Description": "New Branch",
                    "BranchLogic": {
                      "0": {
                        "0": {
                          "LogicType": "Question",
                          "QuestionID": "QID50",
                          "QuestionIsInLoop": "no",
                          "ChoiceLocator": "q://QID50/SelectableChoice/1",
                          "Operator": "Selected",
                          "QuestionIDFromLocator": "QID50",
                          "LeftOperand": "q://QID50/SelectableChoice/1",
                          "Type": "Expression",
                          "Description": "<span class=\"ConjDesc\">If</span> <span class=\"QuestionDesc\">Still having issues?</span> <span class=\"LeftOpDesc\">Check this box to continue.</span> <span class=\"OpDesc\">Is Selected</span> "
                        },
                        "Type": "If"
                      },
                      "Type": "BooleanExpression"
                    },
                    "Flow": [
                      {
                        "Type": "EndSurvey",
                        "FlowID": "FL_44",
                        "EndingType": "Advanced",
                        "Options": {
                          "Advanced": "true",
                          "EmailThankYou": "",
                          "SurveyTermination": "DisplayMessage",
                          "CountQuotas": "No",
                          "AnonymizeResponse": "Yes",
                          "IgnoreResponse": "Yes",
                          "ResponseFlag": "Screened",
                          "EOSMessageLibrary": "UR_bQHormGseyEZkzz",
                          "EOSMessage": "MS_etSVKCFPWkNmA06"
                        }
                      }
                    ]
                  }
                ]
              },
              {
                "Type": "Branch",
                "FlowID": "FL_40",
                "Description": "New Branch",
                "BranchLogic": {
                  "0": {
                    "0": {
                      "LogicType": "Question",
                      "QuestionID": "QID48",
                      "QuestionIsInLoop": "no",
                      "ChoiceLocator": "q://QID48/SelectableChoice/2",
                      "Operator": "Selected",
                      "QuestionIDFromLocator": "QID48",
                      "LeftOperand": "q://QID48/SelectableChoice/2",
                      "Type": "Expression",
                      "Description": "<span class=\"ConjDesc\">If</span> <span class=\"QuestionDesc\">Having issues receiving the code?</span> <span class=\"LeftOpDesc\">Check this box to correct your email address.</span> <span class=\"OpDesc\">Is Selected</span> "
                    },
                    "Type": "If"
                  },
                  "Type": "BooleanExpression"
                },
                "Flow": [
                  {
                    "Type": "Block",
                    "ID": "BL_3xyVR7mBcg6zsy2",
                    "FlowID": "FL_41",
                    "Autofill": []
                  },
                  {
                    "Type": "EmbeddedData",
                    "FlowID": "FL_39",
                    "EmbeddedData": [
                      {
                        "Description": "primary_email_verification",
                        "Type": "Custom",
                        "Field": "primary_email_verification",
                        "VariableType": "String",
                        "DataVisibility": [],
                        "AnalyzeText": false,
                        "Value": "$${rand://int/1000:9999}"
                      }
                    ]
                  },
                  {
                    "Type": "WebService",
                    "FlowID": "FL_42",
                    "URL": "https://hooks.airtable.com/workflows/v1/genericWebhook/appVTPUUDF3ADmhzt/wflXjGYq8j3n31dRg/wtrW3iL7AWJdE34uY",
                    "Method": "POST",
                    "RequestParams": [],
                    "EditBodyParams": [
                      {
                        "key": "code",
                        "value": "$${e://Field/primary_email_verification}"
                      },
                      {
                        "key": "email",
                        "value": "$${q://QID3/ChoiceTextEntryValue}"
                      }
                    ],
                    "Body": {
                      "code": "$${e://Field/primary_email_verification}",
                      "email": "$${q://QID3/ChoiceTextEntryValue}"
                    },
                    "ContentType": "application/json",
                    "Headers": [],
                    "ResponseMap": [],
                    "FireAndForget": false,
                    "SchemaVersion": 0,
                    "StringifyValues": true
                  },
                  {
                    "Type": "Standard",
                    "ID": "BL_8G3NLOlCdaTUwGq",
                    "FlowID": "FL_37",
                    "Autofill": []
                  },
                  {
                    "Type": "Branch",
                    "FlowID": "FL_46",
                    "Description": "New Branch",
                    "BranchLogic": {
                      "0": {
                        "0": {
                          "LogicType": "Question",
                          "QuestionID": "QID52",
                          "QuestionIsInLoop": "no",
                          "ChoiceLocator": "q://QID52/SelectableChoice/1",
                          "Operator": "Selected",
                          "QuestionIDFromLocator": "QID52",
                          "LeftOperand": "q://QID52/SelectableChoice/1",
                          "Type": "Expression",
                          "Description": "<span class=\"ConjDesc\">If</span> <span class=\"QuestionDesc\">Still having issues?</span> <span class=\"LeftOpDesc\">Check this box to continue.</span> <span class=\"OpDesc\">Is Selected</span> "
                        },
                        "Type": "If"
                      },
                      "Type": "BooleanExpression"
                    },
                    "Flow": [
                      {
                        "Type": "EndSurvey",
                        "FlowID": "FL_45",
                        "EndingType": "Advanced",
                        "Options": {
                          "Advanced": "true",
                          "EmailThankYou": "",
                          "SurveyTermination": "DisplayMessage",
                          "CountQuotas": "No",
                          "AnonymizeResponse": "Yes",
                          "IgnoreResponse": "Yes",
                          "ResponseFlag": "Screened",
                          "EOSMessageLibrary": "UR_bQHormGseyEZkzz",
                          "EOSMessage": "MS_etSVKCFPWkNmA06"
                        }
                      }
                    ]
                  }
                ]
              }
            ]
          },
          {
            "Type":"Branch",
            "FlowID":"FL_59",
            "Description":"New Branch",
            "BranchLogic":{
                "0":{
                  "0":{
                      "LogicType":"Question",
                      "QuestionID":"QID3",
                      "QuestionIsInLoop":"no",
                      "ChoiceLocator":"q:\/\/QID3\/ChoiceTextEntryValue",
                      "Operator":"Contains",
                      "QuestionIDFromLocator":"QID3",
                      "LeftOperand":"q:\/\/QID3\/ChoiceTextEntryValue",
                      "RightOperand":"@RCT@",
                      "IgnoreCase":1,
                      "Type":"Expression",
                      "Description":"<span class=\"ConjDesc\">If<\/span> <span class=\"QuestionDesc\">Academic Email Use the same email you used to complete the assignment earlier this semester, even...<\/span> <span class=\"LeftOpDesc\">Text Response<\/span> <span class=\"OpDesc\">Contains<\/span> <span class=\"RightOpDesc\"> @RCT@ <\/span>"
                  },
                  "Type":"If"
                },
                "Type":"BooleanExpression"
            },
            "Flow":[
                {
                  "Type":"EndSurvey",
                  "FlowID":"FL_60",
                  "EndingType":"Advanced",
                  "Options":{
                      "Advanced":"true",
                      "SurveyTermination":"DisplayMessage",
                      "EOSMessageLibrary":"UR_bQHormGseyEZkzz",
                      "EOSMessage":"MS_d4CsfOr3LWsJfwy",
                      "CountQuotas":"No",
                      "AnonymizeResponse":"Yes",
                      "EmailThankYou":"",
                      "IgnoreResponse":"Yes",
                      "ResponseFlag":"Screened"
                  }
                }
            ]
          },
          {
            "Type": "Standard",
            "ID": "BL_b9Gvnb6ouT0YN3U",
            "FlowID": "FL_15",
            "Autofill": []
          },
          {
            "Type": "Standard",
            "ID": "BL_eXTDb32KHtQmrCC",
            "FlowID": "FL_7",
            "Autofill": []
          },
          {
            "Type": "Standard",
            "ID": "BL_4NPsuuYPXBL98RU",
            "FlowID": "FL_8",
            "Autofill": []
          },
          {
            "Type": "Standard",
            "ID": "BL_9QwB36qPFHdIDBk",
            "FlowID": "FL_9",
            "Autofill": []
          },
          {
            "Type": "Standard",
            "ID": "BL_9Zit4slSWS66C3Q",
            "FlowID": "FL_11",
            "Autofill": []
          },
          {
            "Type": "Standard",
            "ID": "BL_2sDajWT9TUHCpdI",
            "FlowID": "FL_12",
            "Autofill": []
          },
          {
            "Type": "Standard",
            "ID": "BL_5zM85wHhtCUK75k",
            "FlowID": "FL_13",
            "Autofill": []
          },
          {
            "Type": "Standard",
            "ID": "BL_6tept7fmRvGOKq2",
            "FlowID": "FL_14",
            "Autofill": []
          },
          {
            "Type": "Standard",
            "ID": "BL_eDp7soVERGKBjPo",
            "FlowID": "FL_10",
            "Autofill": []
          },
          {
            "Type": "Standard",
            "ID": "BL_4HkRdnR2XTOq5tI",
            "FlowID": "FL_48",
            "Autofill": []
          },
          {
            "Type": "Standard",
            "ID": "BL_easvL0yqaT6vGjI",
            "FlowID": "FL_49",
            "Autofill": []
          },
          {
            "Type": "Standard",
            "ID": "BL_2gwh3Zh9Q3Nsn3g",
            "FlowID": "FL_4",
            "Autofill": []
          },
          {
            "Type": "EndSurvey",
            "FlowID": "FL_31"
          }
        ],
        "Properties": {
          "Count": 57
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "PL",
      "PrimaryAttribute": "Preview Link",
      "SecondaryAttribute": null,
      "TertiaryAttribute": null,
      "Payload": {
        "PreviewType": "Brand",
        "PreviewID": "ae0d76e2-c2f7-456e-8a9c-846894178b68"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "PROJ",
      "PrimaryAttribute": "CORE",
      "SecondaryAttribute": null,
      "TertiaryAttribute": "1.1.0",
      "Payload": {
        "ProjectCategory": "CORE",
        "SchemaVersion": "1.1.0"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "QC",
      "PrimaryAttribute": "Survey Question Count",
      "SecondaryAttribute": "74",
      "TertiaryAttribute": null,
      "Payload": null
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "RS",
      "PrimaryAttribute": "RS_8ukqoqmF9idDUai",
      "SecondaryAttribute": null,
      "TertiaryAttribute": null,
      "Payload": null
    },
    {
        "SurveyID":"SV_eP5ggSR1YMcI2HA",
        "Element":"SCO",
        "PrimaryAttribute":"Scoring",
        "SecondaryAttribute":null,
        "TertiaryAttribute":null,
        "Payload":{
          "ScoringCategories":[
              {
                "ID":"SC_78JgOoF7SGSRmAe",
                "Name":"Assignment Score",
                "Description":""
              }
          ],
          "ScoringCategoryGroups":[

          ],
          "DefaultScoringCategory":"SC_78JgOoF7SGSRmAe",
          "ScoringSummaryCategory":null,
          "ScoringSummaryAfterQuestions":0,
          "ScoringSummaryAfterSurvey":0,
          "AutoScoringCategory":null
        }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SO",
      "PrimaryAttribute": "Survey Options",
      "SecondaryAttribute": null,
      "TertiaryAttribute": null,
      "Payload": {
        "BackButton": "true",
        "SaveAndContinue": "true",
        "SurveyProtection": "PublicSurvey",
        "BallotBoxStuffingPrevention": "false",
        "NoIndex": "Yes",
        "SecureResponseFiles": "false",
        "SurveyExpiration": "None",
        "SurveyTermination": "DisplayMessage",
        "Header": "",
        "Footer": "$Footer",
        "ProgressBarDisplay": "None",
        "PartialData": "No",
        "ValidationMessage": null,
        "PreviousButton": "",
        "NextButton": "",
        "SurveyTitle": "$CourseName - End of Semester Form",
        "SkinLibrary": "harvard",
        "SkinType": "component",
        "Skin": {
          "brandingId": "4347843028",
          "templateId": "*simple",
          "overrides": null
        },
        "NewScoring": 1,
        "SurveyMetaDescription": "The most powerful, simple and trusted way to gather experience data. Start your journey to experience management and try a free account today.",
        "CustomStyles": [],
        "EOSMessage": "MS_0UPLHEpEpMrEtGC",
        "ShowExportTags": "false",
        "CollectGeoLocation": "false",
        "PasswordProtection": "No",
        "AnonymizeResponse": "No",
        "RefererCheck": "No",
        "BallotBoxStuffingPreventionBehavior": null,
        "BallotBoxStuffingPreventionMessage": null,
        "BallotBoxStuffingPreventionMessageLibrary": null,
        "BallotBoxStuffingPreventionURL": null,
        "RecaptchaV3": "false",
        "ConfirmStart": false,
        "AutoConfirmStart": false,
        "RelevantID": "false",
        "RelevantIDLockoutPeriod": "+30 days",
        "UseCustomSurveyLinkCompletedMessage": null,
        "SurveyLinkCompletedMessage": null,
        "SurveyLinkCompletedMessageLibrary": null,
        "ResponseSummary": "No",
        "EOSMessageLibrary": "UR_bQHormGseyEZkzz",
        "EOSRedirectURL": "http://",
        "EmailThankYou": "false",
        "ThankYouEmailMessageLibrary": null,
        "ThankYouEmailMessage": null,
        "ValidateMessage": "false",
        "ValidationMessageLibrary": null,
        "InactiveSurvey": "DefaultMessage",
        "PartialDeletion": "+2 weeks",
        "PartialDataCloseAfter": "LastActivity",
        "InactiveMessageLibrary": null,
        "InactiveMessage": null,
        "AvailableLanguages": {
          "EN": []
        },
        "SurveyAnalysisDisabled": true,
        "headerMid": "",
        "footerMid": "",
        "ProtectSelectionIds": true
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID10",
      "SecondaryAttribute": "Timing",
      "TertiaryAttribute": null,
      "Payload": {
        "Choices": {
          "1": {
            "Display": "First Click"
          },
          "2": {
            "Display": "Last Click"
          },
          "3": {
            "Display": "Page Submit"
          },
          "4": {
            "Display": "Click Count"
          }
        },
        "Configuration": {
          "MaxSeconds": "0",
          "MinSeconds": "0",
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A1T",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData": [],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 24,
        "QuestionDescription": "Timing",
        "QuestionID": "QID10",
        "QuestionText": "Timing",
        "QuestionText_Unsafe": "Timing",
        "QuestionType": "Timing",
        "Selector": "PageTimer"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID11",
      "SecondaryAttribute": "Question 2/10.",
      "TertiaryAttribute": null,
      "Payload": {
        "ChoiceOrder": $A2ChoiceOrder,
        "Choices": $A2Choices,
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A2",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData":[
            {
              "ChoiceID":"$A2CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 6,
        "QuestionID": "QID11",
        "QuestionText": "$A2QuestionText",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "Randomization": {
          "Advanced": null,
          "TotalRandSubset": "",
          "Type": "None"
        },
        "RecodeValues": $A2RecodeValues,
        "QuestionJS": $A2JavaScript
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID12",
      "SecondaryAttribute": "Timing",
      "TertiaryAttribute": null,
      "Payload": {
        "Choices": {
          "1": {
            "Display": "First Click"
          },
          "2": {
            "Display": "Last Click"
          },
          "3": {
            "Display": "Page Submit"
          },
          "4": {
            "Display": "Click Count"
          }
        },
        "Configuration": {
          "MaxSeconds": "0",
          "MinSeconds": "0",
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A2T",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData": [],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 24,
        "QuestionDescription": "Timing",
        "QuestionID": "QID12",
        "QuestionText": "Timing",
        "QuestionText_Unsafe": "Timing",
        "QuestionType": "Timing",
        "Selector": "PageTimer"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID13",
      "SecondaryAttribute": "Question 3/10.",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "$A3QuestionText",
        "DefaultChoices": false,
        "DataExportTag": "A3",
        "QuestionID": "QID13",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "Choices": $A3Choices,
        "ChoiceOrder": $A3ChoiceOrder,
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "GradingData":[
            {
              "ChoiceID":"$A3CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language": [],
        "NextChoiceId": 9,
        "NextAnswerId": 1,
        "RecodeValues": $A3RecodeValues,
        "Randomization": {
          "Advanced": null,
          "TotalRandSubset": "",
          "Type": "None"
        },
        "QuestionJS": $A3JavaScript
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID14",
      "SecondaryAttribute": "Timing",
      "TertiaryAttribute": null,
      "Payload": {
        "Choices": {
          "1": {
            "Display": "First Click"
          },
          "2": {
            "Display": "Last Click"
          },
          "3": {
            "Display": "Page Submit"
          },
          "4": {
            "Display": "Click Count"
          }
        },
        "Configuration": {
          "MaxSeconds": "0",
          "MinSeconds": "0",
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A3T",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData": [],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 48,
        "QuestionDescription": "Timing",
        "QuestionID": "QID14",
        "QuestionText": "Timing",
        "QuestionText_Unsafe": "Timing",
        "QuestionType": "Timing",
        "Selector": "PageTimer"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID15",
      "SecondaryAttribute": "Question 4/10.",
      "TertiaryAttribute": null,
      "Payload": {
        "ChoiceOrder": $A4ChoiceOrder,
        "Choices": $A4Choices,
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A4",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData":[
            {
              "ChoiceID":"$A4CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 6,
        "QuestionID": "QID15",
        "QuestionText": "$A4QuestionText",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "Randomization": {
          "Advanced": null,
          "TotalRandSubset": "",
          "Type": "None"
        },
        "RecodeValues": $A4RecodeValues,
        "QuestionJS": $A4JavaScript
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID16",
      "SecondaryAttribute": "Timing",
      "TertiaryAttribute": null,
      "Payload": {
        "Choices": {
          "1": {
            "Display": "First Click"
          },
          "2": {
            "Display": "Last Click"
          },
          "3": {
            "Display": "Page Submit"
          },
          "4": {
            "Display": "Click Count"
          }
        },
        "Configuration": {
          "MaxSeconds": "0",
          "MinSeconds": "0",
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A4T",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData": [],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 28,
        "QuestionDescription": "Timing",
        "QuestionID": "QID16",
        "QuestionText": "Timing",
        "QuestionText_Unsafe": "Timing",
        "QuestionType": "Timing",
        "Selector": "PageTimer"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID17",
      "SecondaryAttribute": "Question 5/10.",
      "TertiaryAttribute": null,
      "Payload": {
        "ChoiceOrder": $A5ChoiceOrder,
        "Choices": $A5Choices,
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A5",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData":[
            {
              "ChoiceID":"$A5CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 6,
        "QuestionID": "QID17",
        "QuestionText": "$A5QuestionText",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "Randomization": {
          "Advanced": null,
          "TotalRandSubset": "",
          "Type": "None"
        },
        "RecodeValues": $A5RecodeValues,
        "QuestionJS": $A5JavaScript
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID18",
      "SecondaryAttribute": "Timing",
      "TertiaryAttribute": null,
      "Payload": {
        "Choices": {
          "1": {
            "Display": "First Click"
          },
          "2": {
            "Display": "Last Click"
          },
          "3": {
            "Display": "Page Submit"
          },
          "4": {
            "Display": "Click Count"
          }
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A5T",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData": [],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 56,
        "QuestionDescription": "Timing",
        "QuestionID": "QID18",
        "QuestionText": "Timing",
        "QuestionText_Unsafe": "Timing",
        "QuestionType": "Timing",
        "Selector": "PageTimer"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID19",
      "SecondaryAttribute": "Question 6/10.",
      "TertiaryAttribute": null,
      "Payload": {
        "ChoiceOrder": $A6ChoiceOrder,
        "Choices": $A6Choices,
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A6",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData":[
            {
              "ChoiceID":"$A6CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 6,
        "QuestionID": "QID19",
        "QuestionText": "$A6QuestionText",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "Randomization": {
          "Advanced": null,
          "TotalRandSubset": "",
          "Type": "None"
        },
        "RecodeValues": $A6RecodeValues,
        "QuestionJS": $A6JavaScript
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID2",
      "SecondaryAttribute": "Full Name",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "Full Name",
        "DefaultChoices": false,
        "DataExportTag": "Intro_Name",
        "QuestionType": "TE",
        "Selector": "SL",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "Full Name",
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None",
            "MinChars": "1",
            "ValidDateType": "DateWithFormat",
            "ValidPhoneType": "ValidUSPhone",
            "ValidZipType": "ValidUSZip",
            "ValidNumber": {
              "Min": "",
              "Max": "",
              "NumDecimals": ""
            }
          }
        },
        "GradingData": [],
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "SearchSource": {
          "AllowFreeResponse": "false"
        },
        "QuestionID": "QID2"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID20",
      "SecondaryAttribute": "Timing",
      "TertiaryAttribute": null,
      "Payload": {
        "Choices": {
          "1": {
            "Display": "First Click"
          },
          "2": {
            "Display": "Last Click"
          },
          "3": {
            "Display": "Page Submit"
          },
          "4": {
            "Display": "Click Count"
          }
        },
        "Configuration": {
          "MaxSeconds": "0",
          "MinSeconds": "0",
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A6T",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData": [],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 28,
        "QuestionDescription": "Timing",
        "QuestionID": "QID20",
        "QuestionText": "Timing",
        "QuestionText_Unsafe": "Timing",
        "QuestionType": "Timing",
        "Selector": "PageTimer"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID23",
      "SecondaryAttribute": "Question 8/10.",
      "TertiaryAttribute": null,
      "Payload": {
        "ChoiceOrder": $A8ChoiceOrder,
        "Choices": $A8Choices,
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A8",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData":[
            {
              "ChoiceID":"$A8CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 11,
        "QuestionID": "QID23",
        "QuestionText": "$A8QuestionText",
        "QuestionType": "MC",
        "Randomization": {
          "Advanced": null,
          "TotalRandSubset": "",
          "Type": "None"
        },
        "Selector": "SAVR",
        "SubSelector": "TX",
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "RecodeValues": $A8RecodeValues,
        "QuestionJS": $A8JavaScript
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID24",
      "SecondaryAttribute": "Timing",
      "TertiaryAttribute": null,
      "Payload": {
        "Choices": {
          "1": {
            "Display": "First Click"
          },
          "2": {
            "Display": "Last Click"
          },
          "3": {
            "Display": "Page Submit"
          },
          "4": {
            "Display": "Click Count"
          }
        },
        "Configuration": {
          "MaxSeconds": "0",
          "MinSeconds": "0",
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A8T",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData": [],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 28,
        "QuestionDescription": "Timing",
        "QuestionID": "QID24",
        "QuestionText": "Timing",
        "QuestionText_Unsafe": "Timing",
        "QuestionType": "Timing",
        "Selector": "PageTimer"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID25",
      "SecondaryAttribute": "Question 7/10.",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "$A7QuestionText",
        "DefaultChoices": false,
        "DataExportTag": "A7",
        "QuestionID": "QID25",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "Choices": $A7Choices,
        "ChoiceOrder": $A7ChoiceOrder,
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "GradingData":[
            {
              "ChoiceID":"$A7CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language": [],
        "NextChoiceId": 9,
        "NextAnswerId": 1,
        "RecodeValues": $A7RecodeValues,
        "Randomization": {
          "Advanced": null,
          "TotalRandSubset": "",
          "Type": "None"
        },
        "QuestionJS": $A7JavaScript
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID26",
      "SecondaryAttribute": "Timing",
      "TertiaryAttribute": null,
      "Payload": {
        "Choices": {
          "1": {
            "Display": "First Click"
          },
          "2": {
            "Display": "Last Click"
          },
          "3": {
            "Display": "Page Submit"
          },
          "4": {
            "Display": "Click Count"
          }
        },
        "Configuration": {
          "MaxSeconds": "0",
          "MinSeconds": "0",
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A7T",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData": [],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 28,
        "QuestionDescription": "Timing",
        "QuestionID": "QID26",
        "QuestionText": "Timing",
        "QuestionText_Unsafe": "Timing",
        "QuestionType": "Timing",
        "Selector": "PageTimer"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID28",
      "SecondaryAttribute": "The first part of your course’s assignment includes 10 multiple-choice questions. The assignment..",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "The <strong>first part</strong> of your course’s assignment includes 10 multiple-choice questions.<br>\n<br>\nThe assignment should take about 15 minutes to finish. Please find a quiet place where you can focus without distractions. Remember: you should complete this on your own without using tools like ChatGPT.<br>\n<br>\nYou will receive full credit for completing the assignment, regardless of how quickly you finish or how many answers are correct.&nbsp;Your individual responses <strong>will not</strong> be shared with your instructor.",
        "DefaultChoices": false,
        "DataExportTag": "A_Intro",
        "QuestionType": "DB",
        "Selector": "TB",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "The first part of your course’s assignment includes 10 multiple-choice questions. The assignment...",
        "ChoiceOrder": [],
        "Validation": {
          "Settings": {
            "Type": "None"
          }
        },
        "GradingData": [],
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "QuestionID": "QID28"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID3",
      "SecondaryAttribute": "Academic Email Use the same email you used to complete the assignment earlier this semester, even...",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "Academic Email<br>\n<span style=\"color:#555555;\"><em>Use the same email you used to complete the assignment earlier this semester, even if it was not your academic email.&nbsp;</em></span>",
        "DefaultChoices": false,
        "DataExportTag": "Intro_Email",
        "QuestionID": "QID3",
        "QuestionType": "TE",
        "Selector": "SL",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "Academic Email Use the same email you used to complete the assignment earlier this semester, even...",
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "CustomValidation",
            "MinChars": "1",
            "ValidDateType": "DateWithFormat",
            "ValidPhoneType": "ValidUSPhone",
            "ValidZipType": "ValidUSZip",
            "ValidNumber": {
              "Min": "",
              "Max": "",
              "NumDecimals": ""
            },
            "CustomValidation": {
              "Logic": {
                "0": {
                  "0": {
                    "QuestionID": "QID3",
                    "QuestionIsInLoop": "no",
                    "ChoiceLocator": "q://QID3/ChoiceTextEntryValue",
                    "Operator": "MatchesRegex",
                    "QuestionIDFromLocator": "QID3",
                    "LeftOperand": "q://QID3/ChoiceTextEntryValue",
                    "RightOperand": "/@RCT@|[^@]+@[^@]+.[^@]+$$/gmi",
                    "Type": "Expression",
                    "LogicType": "Question",
                    "Description": "<span class=\"ConjDesc\">If</span> <span class=\"QuestionDesc\">Academic Email Use the same email you used to complete the assignment earlier this semester, even...</span> <span class=\"LeftOpDesc\">Text Response</span> <span class=\"OpDesc\">Matches Regex</span> <span class=\"RightOpDesc\"> /@RCT@|[^@]+@[^@]+.[^@]+$$/gmi </span>"
                  },
                  "Type": "If"
                },
                "Type": "BooleanExpression"
              },
              "Message": {
                "messageID": null,
                "subMessageID": "VE_VALIDEMAIL",
                "libraryID": null,
                "description": "Require valid email address"
              }
            }
          }
        },
        "GradingData": [],
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "SearchSource": {
          "AllowFreeResponse": "false"
        },
        "QuestionJS": "Qualtrics.SurveyEngine.addOnload(function() {\n    let questionElement = document.getElementById(\"question-QID73\");\n\tlet initCounter = parseInt(Qualtrics.SurveyEngine.getJSEmbeddedData('failed_attempts_email'), 10);\n\tif (initCounter < 2) {\n\t\tquestionElement.style.display = 'none';\n\t}\n\t\n    var qthis = this;  // Reference to the current question context\n\n    // Update this selector based on which input holds the email.\n    var codeSelector = \"#question-QID3 .text-input\";  // adjust as needed\n\n    // Intercept the Next button using its current ID in the new layout.\n    jQuery(\"#next-button\").off(\"click.emailCheck\").on(\"click.emailCheck\", function(event) {\n        // Prevent default actions and propagation.\n        event.preventDefault();\n        event.stopImmediatePropagation();\n\t\t\n\t\tlet overrideCheckbox = document.getElementById(\"mc-choice-input-QID73-1\");\n\t\tif (overrideCheckbox.checked) {\n\t\t\tqthis.clickNextButton();\n\t\t\treturn false;\n\t\t};\n\n        // Get the code entered by the user.\n        var userEmail = jQuery(codeSelector).val();\n\t\t\n\t\tif (userEmail.toLowerCase().trim()===\"@rct@\") {\n\t\t\tqthis.clickNextButton();\n\t\t\treturn false;\n\t\t};\n\t\t\n\t\tvar courseId = \"$${e://Field/pp_airtable_class_RID}\"\n\n        // Make an API call to Airtable to verify the code.\n\t\tvar formula = \"https://api.airtable.com/v0/appVTPUUDF3ADmhzt/tbllpDp4BmwvAwcBi?filterByFormula=\" + \"AND(FIND('$$' %26 LOWER(TRIM('\"+ encodeURIComponent(userEmail.trim()) + \"')) %26 '$$', LOWER({fldUdjbup523cqlXV})) > 0, FIND('\" + courseId + \"', {fldmegozy8Ixm3GTZ}) > 0)\";\n\n\t\tjQuery.ajax({\n            url: formula,\n            method: \"GET\",\n            headers: {\n                \"Authorization\": \"Bearer patn1udOzwDD2iUiM.5bb8f4e3568c1d149df9c401ae6a312bdb4c94c0b26e52fc47592043d4c1d177\"\n            },\n            success: function(response) {\n                // Check if at least one record is returned\n                if (response.records && response.records.length > 0 && response.records[0].id) {\n                    // Email is valid – proceed to the next page.\n\t\t\t\t\tQualtrics.SurveyEngine.setJSEmbeddedData(\"airtable_student_RID\", response.records[0].id);\n                    qthis.clickNextButton();\n                } else {\n                    // No valid records were found.\n\t\t\t\t\tvar counter = parseInt(Qualtrics.SurveyEngine.getJSEmbeddedData('failed_attempts_email'), 10);\n\t\t\t\t\tQualtrics.SurveyEngine.setJSEmbeddedData(\"failed_attempts_email\", counter + 1);\n\t\t\t\t\tcounter = parseInt(Qualtrics.SurveyEngine.getJSEmbeddedData('failed_attempts_email'), 10);\n\t\t\t\t\tif (counter > 1) {\n\t\t\t\t\t\talert(\"We're still having trouble finding your record.\\n\\nIf you're certain you completed the previous assignment for this class with this email, check the \\\"Still having issues\\\" checkbox to continue.\");\n\t\t\t\t\t\tquestionElement.style.display = 'block';\n\t\t\t\t\t\treturn false;\n\t\t\t\t\t}\n                    alert(\"We don't have a record of the email address you entered as enrolled in this class.\\n\\nPlease try again. Make sure to use the same email you used to complete the assignment earlier this semester, even if it was not your academic email.\");\n                }\n            },\n            error: function(error) {\n                // Handle errors in the API call\n\t\t\t\tconsole.log(error);\n                alert(\"There was an error contacting the server. Please try again later. If the issue persists, contact your instructor or email pingpongedu@hks.harvard.edu\");\n            }\n        });\n\n        // Returning false ensures that no other click events are triggered.\n        return false;\n    });\n});\n\nQualtrics.SurveyEngine.addOnReady(function()\n{\n\t/*Place your JavaScript here to run when the page is fully displayed*/\n\n});\n\nQualtrics.SurveyEngine.addOnUnload(function()\n{\n\tQualtrics.SurveyEngine.setJSEmbeddedData(\"failed_attempts_email\", 0);\n\t/*Place your JavaScript here to run when the page is unloaded*/\n\tjQuery(\"#next-button\").off(\"click.emailCheck\");\n\n});"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID35",
      "SecondaryAttribute": "You have now completed the first part of your course's assignment. Please continue with the secon..",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "You have now completed the first part of your course's assignment.&nbsp;<strong>Please continue with the second part of the assignment. Your participation will not be recorded until you submit the survey.</strong><br>\n<br>\nWe'll now ask you some questions about your experience in&nbsp;$${e://Field/pp_class_name}. You will receive full credit for completing the assignment, regardless of your answers to these questions. Your individual responses will not be shared with your instructor. Only anonymous, aggregated responses will be shared with your instructor.",
        "DefaultChoices": false,
        "DataExportTag": "Affective_Intro",
        "QuestionID": "QID35",
        "QuestionType": "DB",
        "Selector": "TB",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText",
          "IncludeDescription": "ON"
        },
        "QuestionDescription": "You have now completed the first part of your course's assignment. Please continue with the secon...",
        "ChoiceOrder": [],
        "Validation": {
          "Settings": {
            "Type": "None"
          }
        },
        "GradingData": [],
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "Files": "F_3Q1hO1TwHE2THf0",
        "FilesDescription": "Education Study Consent Form  Students ",
        "QuestionJS": false
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID47",
      "SecondaryAttribute": "Let's make sure we got the right email address. Enter the verification code we just sent to ...",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "Let&#39;s make sure we got the right email address. Enter the verification code we just sent to&nbsp;$${q://QID3/ChoiceTextEntryValue}.<br />\n<br />\n<span style=\"color:#555555;\"><em>The code might take up to 30 seconds to arrive. Please wait before requesting a new code.&nbsp;</em></span>",
        "DefaultChoices": false,
        "DataExportTag": "Q36",
        "QuestionType": "TE",
        "Selector": "SL",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "Let's make sure we got the right email address. Enter the verification code we just sent to ...",
        "Validation": {
          "Settings": {
            "ForceResponse": "OFF",
            "ForceResponseType": "ON",
            "Type": "CustomValidation",
            "MinChars": "1",
            "CustomValidation": {
              "Logic": {
                "0": {
                  "0": {
                    "QuestionID": "QID47",
                    "QuestionIsInLoop": "no",
                    "ChoiceLocator": "q://QID47/ChoiceTextEntryValue",
                    "Operator": "EqualTo",
                    "QuestionIDFromLocator": "QID47",
                    "LeftOperand": "q://QID47/ChoiceTextEntryValue",
                    "RightOperand": "$${e://Field/primary_email_verification}",
                    "Type": "Expression",
                    "LogicType": "Question",
                    "Description": "<span class=\"ConjDesc\">If</span> <span class=\"QuestionDesc\">Let's make sure we got the right email address. Enter the verification code we just sent to&nbsp;...</span> <span class=\"LeftOpDesc\">Text Response</span> <span class=\"OpDesc\">Is Equal to</span> <span class=\"RightOpDesc\"> $${e://Field/primary_email_verification} </span>"
                  },
                  "1": {
                    "QuestionID": "QID48",
                    "QuestionIsInLoop": "no",
                    "ChoiceLocator": "q://QID48/SelectableChoice/1",
                    "Operator": "Selected",
                    "QuestionIDFromLocator": "QID48",
                    "LeftOperand": "q://QID48/SelectableChoice/1",
                    "Type": "Expression",
                    "LogicType": "Question",
                    "Description": "<span class=\"ConjDesc\">Or</span> <span class=\"QuestionDesc\">Having issues receiving the code?</span> <span class=\"LeftOpDesc\">Check this box to resend the code.</span> <span class=\"OpDesc\">Is Selected</span> ",
                    "Conjuction": "Or"
                  },
                  "2": {
                    "QuestionID": "QID48",
                    "QuestionIsInLoop": "no",
                    "ChoiceLocator": "q://QID48/SelectableChoice/2",
                    "Operator": "Selected",
                    "QuestionIDFromLocator": "QID48",
                    "LeftOperand": "q://QID48/SelectableChoice/2",
                    "Type": "Expression",
                    "LogicType": "Question",
                    "Description": "<span class=\"ConjDesc\">Or</span> <span class=\"QuestionDesc\">Having issues receiving the code?</span> <span class=\"LeftOpDesc\">Check this box to correct your email address.</span> <span class=\"OpDesc\">Is Selected</span> ",
                    "Conjuction": "Or"
                  },
                  "Type": "If"
                },
                "Type": "BooleanExpression"
              },
              "Message": {
                "messageID": "MS_ztITUF4LNipeSdj",
                "subMessageID": "VE_CUSTOM_VALIDATION_0",
                "libraryID": "UR_bQHormGseyEZkzz",
                "description": "Email Verification"
              }
            }
          }
        },
        "GradingData": [],
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "SearchSource": {
          "AllowFreeResponse": "false"
        },
        "QuestionID": "QID47"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID48",
      "SecondaryAttribute": "Having issues receiving the code?",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "Having issues receiving the code?",
        "DataExportTag": "Q37",
        "QuestionType": "MC",
        "Selector": "MAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "Having issues receiving the code?",
        "Choices": {
          "1": {
            "Display": "Check this box to resend the code.",
            "ExclusiveAnswer": true
          },
          "2": {
            "Display": "Check this box to correct your email address.",
            "ExclusiveAnswer": true
          }
        },
        "ChoiceOrder": [
          "1",
          "2"
        ],
        "Validation": {
          "Settings": {
            "ForceResponse": "OFF",
            "Type": "None"
          }
        },
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "QuestionID": "QID48",
        "RecodeValues": {
          "1": "1",
          "2": "2"
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID49",
      "SecondaryAttribute": "We resent the verification code to $${q://QID3/ChoiceTextEntryValue}. Enter it below once you rece..",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "We resent the verification code to&nbsp;$${q://QID3/ChoiceTextEntryValue}. Enter it below once you receive it.<br>\n<br>\n<span style=\"color:#555555;\"><em>The code might take up to 30 seconds to arrive.</em></span>",
        "DefaultChoices": false,
        "DataExportTag": "Q38",
        "QuestionType": "TE",
        "Selector": "SL",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "We resent the verification code to $${q://QID3/ChoiceTextEntryValue}. Enter it below once you rece...",
        "Validation": {
          "Settings": {
            "ForceResponse": "OFF",
            "ForceResponseType": "ON",
            "Type": "CustomValidation",
            "MinChars": "1",
            "CustomValidation": {
              "Logic": {
                "0": {
                  "0": {
                    "QuestionID": "QID49",
                    "QuestionIsInLoop": "no",
                    "ChoiceLocator": "q://QID49/ChoiceTextEntryValue",
                    "Operator": "EqualTo",
                    "QuestionIDFromLocator": "QID49",
                    "LeftOperand": "q://QID49/ChoiceTextEntryValue",
                    "RightOperand": "$${e://Field/primary_email_verification}",
                    "Type": "Expression",
                    "LogicType": "Question",
                    "Description": "<span class=\"ConjDesc\">If</span> <span class=\"QuestionDesc\">We resent the verification code to&nbsp;$${q://QID3/ChoiceTextEntryValue}. Enter it below once you rece...</span> <span class=\"LeftOpDesc\">Text Response</span> <span class=\"OpDesc\">Is Equal to</span> <span class=\"RightOpDesc\"> $${e://Field/primary_email_verification} </span>"
                  },
                  "1": {
                    "QuestionID": "QID50",
                    "QuestionIsInLoop": "no",
                    "ChoiceLocator": "q://QID50/SelectableChoice/1",
                    "Operator": "Selected",
                    "QuestionIDFromLocator": "QID50",
                    "LeftOperand": "q://QID50/SelectableChoice/1",
                    "Type": "Expression",
                    "LogicType": "Question",
                    "Description": "<span class=\"ConjDesc\">Or</span> <span class=\"QuestionDesc\">Still having issues?</span> <span class=\"LeftOpDesc\">Check this box to continue.</span> <span class=\"OpDesc\">Is Selected</span> ",
                    "Conjuction": "Or"
                  },
                  "Type": "If"
                },
                "Type": "BooleanExpression"
              },
              "Message": {
                "messageID": "MS_ztITUF4LNipeSdj",
                "subMessageID": "VE_CUSTOM_VALIDATION_0",
                "libraryID": "UR_bQHormGseyEZkzz",
                "description": "Email Verification"
              }
            }
          }
        },
        "GradingData": [],
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "SearchSource": {
          "AllowFreeResponse": "false"
        },
        "QuestionID": "QID49"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID50",
      "SecondaryAttribute": "Still having issues?",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "Still having issues?",
        "DataExportTag": "Q39",
        "QuestionType": "MC",
        "Selector": "MAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "Still having issues?",
        "Choices": {
          "1": {
            "Display": "Check this box to continue.",
            "ExclusiveAnswer": true
          }
        },
        "ChoiceOrder": [
          "1"
        ],
        "Validation": {
          "Settings": {
            "ForceResponse": "OFF",
            "Type": "None"
          }
        },
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "QuestionID": "QID50",
        "RecodeValues": {
          "1": "1"
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID51",
      "SecondaryAttribute": "We sent the verification code to $${q://QID3/ChoiceTextEntryValue}. Enter it below once you receiv..",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "We sent the verification code to&nbsp;$${q://QID3/ChoiceTextEntryValue}. Enter it below once you receive it.<br>\n<br>\n<span style=\"color:#555555;\"><em>The code might take up to 30 seconds to arrive.</em></span>",
        "DefaultChoices": false,
        "QuestionType": "TE",
        "Selector": "SL",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "We sent the verification code to $${q://QID3/ChoiceTextEntryValue}. Enter it below once you receiv...",
        "Validation": {
          "Settings": {
            "ForceResponse": "OFF",
            "ForceResponseType": "ON",
            "Type": "CustomValidation",
            "MinChars": "1",
            "CustomValidation": {
              "Logic": {
                "0": {
                  "0": {
                    "ChoiceLocator": "q://QID51/ChoiceTextEntryValue",
                    "Description": "<span class=\"ConjDesc\">If</span> <span class=\"QuestionDesc\">Sent the verification code to&amp;nbsp;$${q://QID3/ChoiceTextEntryValue}. Enter it below once you receive it.\n\nThe code might take up to 30 seconds to arrive.</span> <span class=\"LeftOpDesc\">Text Response</span> <span class=\"OpDesc\">Is Equal to</span> <span class=\"RightOpDesc\"> $${e://Field/primary_email_verification} </span>",
                    "LeftOperand": "q://QID51/ChoiceTextEntryValue",
                    "LogicType": "Question",
                    "Operator": "EqualTo",
                    "QuestionID": "QID51",
                    "QuestionIDFromLocator": "QID51",
                    "QuestionIsInLoop": "no",
                    "RightOperand": "$${e://Field/primary_email_verification}",
                    "Type": "Expression"
                  },
                  "1": {
                    "ChoiceLocator": "q://QID52/SelectableChoice/1",
                    "Conjuction": "Or",
                    "Description": "<span class=\"ConjDesc\">Or</span> <span class=\"QuestionDesc\">Still having issues?</span> <span class=\"LeftOpDesc\">Check this box to continue.</span> <span class=\"OpDesc\">Is Selected</span> ",
                    "LeftOperand": "q://QID52/SelectableChoice/1",
                    "LogicType": "Question",
                    "Operator": "Selected",
                    "QuestionID": "QID52",
                    "QuestionIDFromLocator": "QID52",
                    "QuestionIsInLoop": "no",
                    "Type": "Expression"
                  },
                  "Type": "If"
                },
                "Type": "BooleanExpression"
              },
              "Message": {
                "description": "Email Verification",
                "libraryID": "UR_bQHormGseyEZkzz",
                "messageID": "MS_ztITUF4LNipeSdj",
                "subMessageID": "VE_CUSTOM_VALIDATION_0"
              }
            }
          }
        },
        "GradingData": [],
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "SearchSource": {
          "AllowFreeResponse": "false"
        },
        "QuestionText_Unsafe": "We resent the verification code to&nbsp;$${q://QID3/ChoiceTextEntryValue}. Enter it below once you receive it.<br>\n<br>\n<span style=\"color:#555555;\"><em>The code might take up to 30 seconds to arrive.</em></span>",
        "DataExportTag": "Q51",
        "QuestionID": "QID51"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID52",
      "SecondaryAttribute": "Still having issues?",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "Still having issues?",
        "QuestionType": "MC",
        "Selector": "MAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "Still having issues?",
        "Choices": {
          "1": {
            "Display": "Check this box to continue.",
            "ExclusiveAnswer": true
          }
        },
        "ChoiceOrder": [
          "1"
        ],
        "Validation": {
          "Settings": {
            "ForceResponse": "OFF",
            "Type": "None",
            "MinChoices": "1"
          }
        },
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "QuestionText_Unsafe": "Still having issues?",
        "DataExportTag": "Q52",
        "QuestionID": "QID52",
        "RecodeValues": {
          "1": "1"
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID53",
      "SecondaryAttribute": "Question 9/10.",
      "TertiaryAttribute": null,
      "Payload": {
        "ChoiceOrder": $A9ChoiceOrder,
        "Choices": $A9Choices,
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A9",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData":[
            {
              "ChoiceID":"$A9CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 9,
        "QuestionID": "QID53",
        "QuestionText": "$A9QuestionText",
        "QuestionType": "MC",
        "Randomization": {
          "Advanced": null,
          "TotalRandSubset": "",
          "Type": "None"
        },
        "Selector": "SAVR",
        "SubSelector": "TX",
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "RecodeValues": $A9RecodeValues,
        "QuestionJS": $A9JavaScript
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID54",
      "SecondaryAttribute": "Timing",
      "TertiaryAttribute": null,
      "Payload": {
        "Choices": {
          "1": {
            "Display": "First Click"
          },
          "2": {
            "Display": "Last Click"
          },
          "3": {
            "Display": "Page Submit"
          },
          "4": {
            "Display": "Click Count"
          }
        },
        "Configuration": {
          "MaxSeconds": "0",
          "MinSeconds": "0",
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A9T",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData": [],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 52,
        "QuestionDescription": "Timing",
        "QuestionID": "QID54",
        "QuestionText": "Timing",
        "QuestionText_Unsafe": "Timing",
        "QuestionType": "Timing",
        "Selector": "PageTimer"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID55",
      "SecondaryAttribute": "Timing",
      "TertiaryAttribute": null,
      "Payload": {
        "Choices": {
          "1": {
            "Display": "First Click"
          },
          "2": {
            "Display": "Last Click"
          },
          "3": {
            "Display": "Page Submit"
          },
          "4": {
            "Display": "Click Count"
          }
        },
        "Configuration": {
          "MaxSeconds": "0",
          "MinSeconds": "0",
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A10T",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData": [],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 40,
        "QuestionDescription": "Timing",
        "QuestionID": "QID55",
        "QuestionText": "Timing",
        "QuestionText_Unsafe": "Timing",
        "QuestionType": "Timing",
        "Selector": "PageTimer"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID56",
      "SecondaryAttribute": "Question 10/10.",
      "TertiaryAttribute": null,
      "Payload": {
        "ChoiceOrder": $A10ChoiceOrder,
        "Choices": $A10Choices,
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "DataExportTag": "A10",
        "DataVisibility": {
          "Hidden": false,
          "Private": false
        },
        "DefaultChoices": false,
        "GradingData":[
            {
              "ChoiceID":"$A10CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language": [],
        "NextAnswerId": 1,
        "NextChoiceId": 9,
        "QuestionID": "QID56",
        "QuestionText": "$A10QuestionText",
        "QuestionType": "MC",
        "Randomization": {
          "Advanced": null,
          "TotalRandSubset": "",
          "Type": "None"
        },
        "Selector": "SAVR",
        "SubSelector": "TX",
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "RecodeValues": $A10RecodeValues,
        "QuestionJS": $A10JavaScript
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID61",
      "SecondaryAttribute": "Question 1/10.",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "$A1QuestionText",
        "DefaultChoices": false,
        "DataExportTag": "A1",
        "QuestionID": "QID61",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "Choices": $A1Choices,
        "ChoiceOrder": $A1ChoiceOrder,
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "GradingData":[
            {
              "ChoiceID":"$A1CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language": [],
        "NextChoiceId": 9,
        "NextAnswerId": 1,
        "RecodeValues": $A1RecodeValues,
        "Randomization": {
          "Advanced": null,
          "TotalRandSubset": "",
          "Type": "None"
        },
        "QuestionJS": $A1JavaScript
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID62",
      "SecondaryAttribute": "How much did you enjoy this course?",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "How much did you enjoy this course?",
        "DefaultChoices": false,
        "DataExportTag": "AQ_1",
        "QuestionID": "QID62",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText",
          "TextPosition": "inline"
        },
        "QuestionDescription": "How much did you enjoy this course?",
        "Choices": {
          "1": {
            "Display": "Not at all"
          },
          "2": {
            "Display": "Slightly"
          },
          "3": {
            "Display": "Moderately"
          },
          "4": {
            "Display": "Very much"
          },
          "5": {
            "Display": "Extremely"
          }
        },
        "ChoiceOrder": [
          "1",
          "2",
          "3",
          "4",
          "5"
        ],
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "GradingData": [],
        "Language": [],
        "NextChoiceId": 6,
        "NextAnswerId": 4,
        "RecodeValues": {
          "1": "1",
          "2": "2",
          "3": "3",
          "4": "4",
          "5": "5"
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID63",
      "SecondaryAttribute": "How much did you learn in this course?",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "How much did you learn in this course?",
        "DataExportTag": "AQ_2",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "How much did you learn in this course?",
        "Choices": {
          "1": {
            "Display": "Nothing"
          },
          "2": {
            "Display": "A little"
          },
          "3": {
            "Display": "A moderate amount"
          },
          "4": {
            "Display": "A substantial amount"
          },
          "5": {
            "Display": "A lot"
          }
        },
        "ChoiceOrder": [
          "1",
          "2",
          "3",
          "4",
          "5"
        ],
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "Language": [],
        "NextChoiceId": 6,
        "NextAnswerId": 1,
        "QuestionID": "QID63",
        "RecodeValues": {
          "1": "1",
          "2": "2",
          "3": "3",
          "4": "4",
          "5": "5"
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID64",
      "SecondaryAttribute": "What generative AI tools, if any, did you use for this course?",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "What generative AI tools, if any, did you use for this course?",
        "DataExportTag": "AQ_4",
        "QuestionType": "MC",
        "Selector": "MAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "What generative AI tools, if any, did you use for this course?",
        "Choices": {
          "1": {
            "Display": "ChatGPT"
          },
          "2": {
            "Display": "Pingpong",
            "DisplayLogic": {
              "0": {
                "0": {
                  "Description": "<span class=\"ConjDesc\">If</span> <span class=\"LeftOpDesc\">pp_randomization</span> <span class=\"OpDesc\">Is Equal to</span> <span class=\"RightOpDesc\"> Treatment </span>",
                  "LeftOperand": "pp_randomization",
                  "LogicType": "EmbeddedField",
                  "Operator": "EqualTo",
                  "RightOperand": "Treatment",
                  "Type": "Expression"
                },
                "Type": "If"
              },
              "Type": "BooleanExpression",
              "inPage": false
            }
          },
          "3": {
            "Display": "Claude"
          },
          "4": {
            "Display": "Perplexity"
          },
          "5": {
            "Display": "Gemini"
          },
          "6": {
            "Display": "Other",
            "TextEntry": "true"
          },
          "7": {
            "Display": "I didn’t use any generative AI tools.",
            "ExclusiveAnswer": true
          }
        },
        "ChoiceOrder": [
          "1",
          "2",
          "3",
          "4",
          "5",
          "6",
          "7"
        ],
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "Language": [],
        "NextChoiceId": 8,
        "NextAnswerId": 1,
        "QuestionID": "QID64",
        "RecodeValues": {
          "1": "1",
          "2": "2",
          "3": "3",
          "4": "4",
          "5": "5",
          "6": "6",
          "7": "7"
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID65",
      "SecondaryAttribute": "How often did you use generative AI for this course?",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "How often did you use generative AI for this course?",
        "DataExportTag": "AQ_5",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "How often did you use generative AI for this course?",
        "Choices": {
          "1": {
            "Display": "Never"
          },
          "2": {
            "Display": "Once or twice throughout the course"
          },
          "3": {
            "Display": "A few times per month"
          },
          "4": {
            "Display": "Every week"
          },
          "5": {
            "Display": "Daily"
          }
        },
        "ChoiceOrder": [
          "1",
          "2",
          "3",
          "4",
          "5"
        ],
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "Language": [],
        "NextChoiceId": 6,
        "NextAnswerId": 1,
        "QuestionID": "QID65",
        "RecodeValues": {
          "1": "1",
          "2": "2",
          "3": "3",
          "4": "4",
          "5": "5"
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID66",
      "SecondaryAttribute": "I would like to see instructor-approved generative AI tools used to support learning in my future...",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "I would like to see instructor-approved generative AI tools used to support learning in my future courses.",
        "DataExportTag": "AQ_6",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "I would like to see instructor-approved generative AI tools used to support learning in my future...",
        "Choices": {
          "1": {
            "Display": "Strongly disagree"
          },
          "2": {
            "Display": "Somewhat disagree"
          },
          "3": {
            "Display": "Neither agree or disagree"
          },
          "4": {
            "Display": "Somewhat agree"
          },
          "5": {
            "Display": "Strongly agree"
          }
        },
        "ChoiceOrder": [
          "1",
          "2",
          "3",
          "4",
          "5"
        ],
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "Language": [],
        "NextChoiceId": 6,
        "NextAnswerId": 1,
        "QuestionID": "QID66",
        "RecodeValues": {
          "1": "1",
          "2": "2",
          "3": "3",
          "4": "4",
          "5": "5"
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID68",
      "SecondaryAttribute": "When I had questions about the course material, I had access to resources to answer them.",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "When I had questions about the course material, I had access to resources to answer them.",
        "DataExportTag": "AQ_3",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "When I had questions about the course material, I had access to resources to answer them.",
        "Choices": {
          "1": {
            "Display": "Strongly disagree"
          },
          "2": {
            "Display": "Somewhat disagree"
          },
          "3": {
            "Display": "Neither agree or disagree"
          },
          "4": {
            "Display": "Somewhat agree"
          },
          "5": {
            "Display": "Strongly agree"
          }
        },
        "ChoiceOrder": [
          "1",
          "2",
          "3",
          "4",
          "5"
        ],
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "Language": [],
        "NextChoiceId": 6,
        "NextAnswerId": 1,
        "QuestionID": "QID68",
        "RecodeValues": {
          "1": "1",
          "2": "2",
          "3": "3",
          "4": "4",
          "5": "5"
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID69",
      "SecondaryAttribute": "Please rate your overall satisfaction with PingPong in terms of supporting your learning:",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "Please rate your overall satisfaction with PingPong in terms of supporting your learning:",
        "DataExportTag": "AQ_7",
        "QuestionType": "MC",
        "Selector": "SAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "Please rate your overall satisfaction with PingPong in terms of supporting your learning:",
        "Choices": {
          "1": {
            "Display": "Very dissatisfied"
          },
          "2": {
            "Display": "Dissatisfied"
          },
          "3": {
            "Display": "Neutral"
          },
          "4": {
            "Display": "Satisfied"
          },
          "5": {
            "Display": "Very satisfied"
          }
        },
        "ChoiceOrder": [
          "1",
          "2",
          "3",
          "4",
          "5"
        ],
        "Validation": {
          "Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None"
          }
        },
        "Language": [],
        "NextChoiceId": 6,
        "NextAnswerId": 1,
        "QuestionID": "QID69",
        "DisplayLogic": {
          "0": {
            "0": {
              "Description": "<span class=\"ConjDesc\">If</span> <span class=\"LeftOpDesc\">pp_randomization</span> <span class=\"OpDesc\">Is Equal to</span> <span class=\"RightOpDesc\"> Treatment </span>",
              "LeftOperand": "pp_randomization",
              "LogicType": "EmbeddedField",
              "Operator": "EqualTo",
              "RightOperand": "Treatment",
              "Type": "Expression"
            },
            "Type": "If"
          },
          "Type": "BooleanExpression",
          "inPage": false
        },
        "RecodeValues": {
          "1": "1",
          "2": "2",
          "3": "3",
          "4": "4",
          "5": "5"
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID70",
      "SecondaryAttribute": "Which aspects of PingPong were MOST helpful for your learning in this course? Feel free to includ...",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "Which aspects of PingPong were <strong>MOST</strong> helpful for your learning in this course? Feel free to include specific situations or tasks where you found PingPong most useful.",
        "DefaultChoices": false,
        "DataExportTag": "AQ_8",
        "QuestionID": "QID70",
        "QuestionType": "TE",
        "Selector": "ML",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "Which aspects of PingPong were MOST helpful for your learning in this course? Feel free to includ...",
        "Validation": {
          "Settings": {
            "ForceResponse": "RequestResponse",
            "ForceResponseType": "RequestResponse",
            "Type": "None"
          }
        },
        "GradingData": [],
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "SearchSource": {
          "AllowFreeResponse": "false"
        },
        "DisplayLogic": {
          "0": {
            "0": {
              "LogicType": "EmbeddedField",
              "LeftOperand": "pp_randomization",
              "Operator": "EqualTo",
              "RightOperand": "Treatment",
              "Type": "Expression",
              "Description": "<span class=\"ConjDesc\">If</span> <span class=\"LeftOpDesc\">pp_randomization</span> <span class=\"OpDesc\">Is Equal to</span> <span class=\"RightOpDesc\"> Treatment </span>"
            },
            "Type": "If"
          },
          "Type": "BooleanExpression",
          "inPage": false
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID72",
      "SecondaryAttribute": "Which aspects of PingPong were LEAST helpful for your learning in this course? Feel free to inclu..",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "Which aspects of PingPong were <strong>LEAST</strong>&nbsp;helpful for your learning in this course? Feel free to include challenges or frustrations you encountered, or anything that was missing that would have made PingPong more useful for you.",
        "DefaultChoices": false,
        "DataExportTag": "AQ_9",
        "QuestionType": "TE",
        "Selector": "ML",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "Which aspects of PingPong were LEAST helpful for your learning in this course? Feel free to inclu...",
        "Validation": {
          "Settings": {
            "ForceResponse": "RequestResponse",
            "ForceResponseType": "RequestResponse",
            "Type": "None"
          }
        },
        "GradingData": [],
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "SearchSource": {
          "AllowFreeResponse": "false"
        },
        "QuestionID": "QID72",
        "DisplayLogic": {
          "0": {
            "0": {
              "LogicType": "EmbeddedField",
              "LeftOperand": "pp_randomization",
              "Operator": "EqualTo",
              "RightOperand": "Treatment",
              "Type": "Expression",
              "Description": "<span class=\"ConjDesc\">If</span> <span class=\"LeftOpDesc\">pp_randomization</span> <span class=\"OpDesc\">Is Equal to</span> <span class=\"RightOpDesc\"> Treatment </span>"
            },
            "Type": "If"
          },
          "Type": "BooleanExpression",
          "inPage": false
        }
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID73",
      "SecondaryAttribute": "Still having issues? Check the box below to continue. We weren't able to find the email you enter...",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "<span style=\"color:#c0392b;\"><strong>Still having issues? Check the box below to continue.</strong></span><br>\n<em>We weren't able to find the email you entered in our records. Please make sure you are using one of the email(s) you entered during the first assignment. As a last resort, check the box below to continue. We will attempt to manually match your name and email to your previous assignment record so your instructor can give you credit.</em>",
        "DataExportTag": "Last_Resort_Email",
        "QuestionType": "MC",
        "Selector": "MAVR",
        "SubSelector": "TX",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "Still having issues? Check the box below to continue. We weren't able to find the email you enter...",
        "Choices": {
          "1": {
            "Display": "Check this box to continue."
          }
        },
        "ChoiceOrder": [
          "1"
        ],
        "Validation": {
          "Settings": {
            "ForceResponse": "OFF",
            "Type": "None"
          }
        },
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "QuestionID": "QID73",
        "RecodeValues": {
          "1": "1"
        }
      }
    },
    {
      "SurveyID":"SV_eyerBD842srQPYO",
      "Element":"SQ",
      "PrimaryAttribute":"QID75",
      "SecondaryAttribute":"Question 4/10.",
      "TertiaryAttribute":null,
      "Payload":{
        "QuestionText": "$A4QuestionText",
        "DefaultChoices":false,
        "DataExportTag":"TEST_A4",
        "QuestionType":"MC",
        "Selector":"SAVR",
        "SubSelector":"TX",
        "DataVisibility":{
            "Private":false,
            "Hidden":false
        },
        "Configuration":{
            "QuestionDescriptionOption":"UseText"
        },
        "Choices": $A4Choices,
        "ChoiceOrder": $A4ChoiceOrder,
        "Randomization":{
            "Advanced":null,
            "TotalRandSubset":"",
            "Type":"None"
        },
        "Validation":{
            "Settings":{
              "ForceResponse":"OFF",
              "ForceResponseType":"ON",
              "Type":"None"
            }
        },
        "RecodeValues": $A4RecodeValues,
        "QuestionJS": "",
        "GradingData":[
            {
              "ChoiceID":"$A4CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language":[

        ],
        "NextChoiceId":6,
        "NextAnswerId":1,
        "QuestionID":"QID75"
      }
    },
    {
      "SurveyID":"SV_eyerBD842srQPYO",
      "Element":"SQ",
      "PrimaryAttribute":"QID76",
      "SecondaryAttribute": "Question 1/10.",
      "TertiaryAttribute":null,
      "Payload":{
        "QuestionText": "$A1QuestionText",
        "DefaultChoices":false,
        "DataExportTag":"TEST_A1",
        "QuestionType":"MC",
        "Selector":"SAVR",
        "SubSelector":"TX",
        "DataVisibility":{
            "Private":false,
            "Hidden":false
        },
        "Configuration":{
            "QuestionDescriptionOption":"UseText"
        },
        "Choices": $A1Choices,
        "ChoiceOrder": $A1ChoiceOrder,
        "Randomization":{
            "Advanced":null,
            "TotalRandSubset":"",
            "Type":"None"
        },
        "Validation":{
            "Settings":{
              "ForceResponse":"OFF",
              "ForceResponseType":"ON",
              "Type":"None"
            }
        },
        "RecodeValues": $A1RecodeValues,
        "GradingData":[
            {
              "ChoiceID":"$A1CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language":[

        ],
        "NextChoiceId":9,
        "NextAnswerId":1,
        "QuestionJS": $TestJavaScript,
        "QuestionID":"QID76"
      }
    },
    {
      "SurveyID":"SV_eyerBD842srQPYO",
      "Element":"SQ",
      "PrimaryAttribute":"QID77",
      "SecondaryAttribute": "Question 2/10.",
      "TertiaryAttribute":null,
      "Payload":{
        "QuestionText": "$A2QuestionText",
        "DefaultChoices":false,
        "DataExportTag":"TEST_A2",
        "QuestionType":"MC",
        "Selector":"SAVR",
        "SubSelector":"TX",
        "DataVisibility":{
            "Private":false,
            "Hidden":false
        },
        "Configuration":{
            "QuestionDescriptionOption":"UseText"
        },
        "Choices": $A2Choices,
        "ChoiceOrder": $A2ChoiceOrder,
        "Randomization":{
            "Advanced":null,
            "TotalRandSubset":"",
            "Type":"None"
        },
        "Validation":{
            "Settings":{
              "ForceResponse":"OFF",
              "ForceResponseType":"ON",
              "Type":"None"
            }
        },
        "RecodeValues": $A2RecodeValues,
        "GradingData":[
            {
              "ChoiceID":"$A2CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language":[

        ],
        "NextChoiceId":6,
        "NextAnswerId":1,
        "QuestionID":"QID77",
        "QuestionJS": ""
      }
    },
    {
      "SurveyID":"SV_eyerBD842srQPYO",
      "Element":"SQ",
      "PrimaryAttribute":"QID79",
      "SecondaryAttribute": "Question 3/10.",
      "TertiaryAttribute":null,
      "Payload":{
        "QuestionText": "$A3QuestionText",
        "DefaultChoices":false,
        "DataExportTag":"TEST_A3",
        "QuestionType":"MC",
        "Selector":"SAVR",
        "SubSelector":"TX",
        "DataVisibility":{
            "Private":false,
            "Hidden":false
        },
        "Configuration":{
            "QuestionDescriptionOption":"UseText"
        },
        "Choices": $A3Choices,
        "ChoiceOrder": $A3ChoiceOrder,
        "Randomization":{
            "Advanced":null,
            "TotalRandSubset":"",
            "Type":"None"
        },
        "Validation":{
            "Settings":{
              "ForceResponse":"OFF",
              "ForceResponseType":"ON",
              "Type":"None"
            }
        },
        "RecodeValues": $A3RecodeValues,
        "GradingData":[
            {
              "ChoiceID":"$A3CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language":[

        ],
        "NextChoiceId":9,
        "NextAnswerId":1,
        "QuestionID":"QID79",
        "QuestionJS": ""
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "SQ",
      "PrimaryAttribute": "QID8",
      "SecondaryAttribute": "Welcome to your second assignment for $${e://Field/pp_class_name}. If you do not recognize this co..",
      "TertiaryAttribute": null,
      "Payload": {
        "QuestionText": "<table align=\"center\" cellpadding=\"15\" cellspacing=\"1\" style=\"width:100%;\">\n\t<tbody>\n\t\t<tr>\n\t\t\t<td style=\"background-color: rgb(235, 244, 255); border-color: rgb(235, 244, 255); text-align: center;\"><span style=\"font-size:24px;\">Welcome to your second&nbsp;assignment for<br />\n\t\t\t$${e://Field/pp_class_name}.<br />\n\t\t\t<br />\n\t\t\t<em><strong>If you do not recognize this course name, do not complete this survey and reach out to your instructor.</strong></em> </span></td>\n\t\t</tr>\n\t</tbody>\n</table>\n<br />\nWe&#39;ll collect your contact information so your instructor can give you credit for completing this assignment.",
        "DefaultChoices": false,
        "DataExportTag": "Intro",
        "QuestionType": "DB",
        "Selector": "TB",
        "DataVisibility": {
          "Private": false,
          "Hidden": false
        },
        "Configuration": {
          "QuestionDescriptionOption": "UseText"
        },
        "QuestionDescription": "Welcome to your second assignment for $${e://Field/pp_class_name}. If you do not recognize this co...",
        "ChoiceOrder": [],
        "Validation": {
          "Settings": {
            "Type": "None"
          }
        },
        "GradingData": [],
        "Language": [],
        "NextChoiceId": 4,
        "NextAnswerId": 1,
        "QuestionID": "QID8"
      }
    },
    {
      "SurveyID":"SV_eyerBD842srQPYO",
      "Element":"SQ",
      "PrimaryAttribute":"QID80",
      "SecondaryAttribute": "Question 5/10.",
      "TertiaryAttribute":null,
      "Payload":{
        "QuestionText": "$A5QuestionText",
        "DefaultChoices":false,
        "DataExportTag":"TEST_A5",
        "QuestionType":"MC",
        "Selector":"SAVR",
        "SubSelector":"TX",
        "DataVisibility":{
            "Private":false,
            "Hidden":false
        },
        "Configuration":{
            "QuestionDescriptionOption":"UseText"
        },
        "Choices": $A5Choices,
        "ChoiceOrder": $A5ChoiceOrder,
        "Randomization":{
            "Advanced":null,
            "TotalRandSubset":"",
            "Type":"None"
        },
        "Validation":{
            "Settings":{
              "ForceResponse":"OFF",
              "ForceResponseType":"ON",
              "Type":"None"
            }
        },
        "RecodeValues": $A5RecodeValues,
        "GradingData":[
            {
              "ChoiceID":"$A5CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language":[

        ],
        "NextChoiceId":6,
        "NextAnswerId":1,
        "QuestionID":"QID80",
        "QuestionJS": ""
      }
    },
    {
      "SurveyID":"SV_eyerBD842srQPYO",
      "Element":"SQ",
      "PrimaryAttribute":"QID81",
      "SecondaryAttribute": "Question 6/10.",
      "TertiaryAttribute":null,
      "Payload":{
        "QuestionText": "$A6QuestionText",
        "DefaultChoices":false,
        "DataExportTag":"TEST_A6",
        "QuestionType":"MC",
        "Selector":"SAVR",
        "SubSelector":"TX",
        "DataVisibility":{
            "Private":false,
            "Hidden":false
        },
        "Configuration":{
            "QuestionDescriptionOption":"UseText"
        },
        "Choices": $A6Choices,
        "ChoiceOrder": $A6ChoiceOrder,
        "Randomization":{
            "Advanced":null,
            "TotalRandSubset":"",
            "Type":"None"
        },
        "Validation":{
            "Settings":{
              "ForceResponse":"OFF",
              "ForceResponseType":"ON",
              "Type":"None"
            }
        },
        "RecodeValues": $A6RecodeValues,
        "GradingData":[
            {
              "ChoiceID":"$A6CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language":[

        ],
        "NextChoiceId":6,
        "NextAnswerId":1,
        "QuestionID":"QID81",
        "QuestionJS": ""
      }
    },
    {
      "SurveyID":"SV_eyerBD842srQPYO",
      "Element":"SQ",
      "PrimaryAttribute":"QID82",
      "SecondaryAttribute": "Question 7/10.",
      "TertiaryAttribute":null,
      "Payload":{
        "QuestionText": "$A7QuestionText",
        "DefaultChoices":false,
        "DataExportTag":"TEST_A7",
        "QuestionType":"MC",
        "Selector":"SAVR",
        "SubSelector":"TX",
        "DataVisibility":{
            "Private":false,
            "Hidden":false
        },
        "Configuration":{
            "QuestionDescriptionOption":"UseText"
        },
        "Choices": $A7Choices,
        "ChoiceOrder": $A7ChoiceOrder,
        "Randomization":{
            "Advanced":null,
            "TotalRandSubset":"",
            "Type":"None"
        },
        "Validation":{
            "Settings":{
              "ForceResponse":"OFF",
              "ForceResponseType":"ON",
              "Type":"None"
            }
        },
        "RecodeValues": $A7RecodeValues,
        "GradingData":[
            {
              "ChoiceID":"$A7CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language":[

        ],
        "NextChoiceId":9,
        "NextAnswerId":1,
        "QuestionID":"QID82",
        "QuestionJS": ""
      }
    },
    {
      "SurveyID":"SV_eyerBD842srQPYO",
      "Element":"SQ",
      "PrimaryAttribute":"QID83",
      "SecondaryAttribute": "Question 8/10.",
      "TertiaryAttribute":null,
      "Payload":{
        "QuestionText": "$A8QuestionText",
        "DefaultChoices":false,
        "DataExportTag":"TEST_A8",
        "QuestionType":"MC",
        "Selector":"SAVR",
        "SubSelector":"TX",
        "DataVisibility":{
            "Private":false,
            "Hidden":false
        },
        "Configuration":{
            "QuestionDescriptionOption":"UseText"
        },
        "Choices": $A8Choices,
        "ChoiceOrder": $A8ChoiceOrder,
        "Randomization":{
            "Advanced":null,
            "TotalRandSubset":"",
            "Type":"None"
        },
        "Validation":{
            "Settings":{
              "ForceResponse":"OFF",
              "ForceResponseType":"ON",
              "Type":"None"
            }
        },
        "RecodeValues": $A8RecodeValues,
        "GradingData":[
            {
              "ChoiceID":"$A8CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language":[

        ],
        "NextChoiceId":11,
        "NextAnswerId":1,
        "QuestionID":"QID83",
        "QuestionJS": ""
      }
    },
    {
      "SurveyID":"SV_eyerBD842srQPYO",
      "Element":"SQ",
      "PrimaryAttribute":"QID84",
      "SecondaryAttribute": "Question 9/10.",
      "TertiaryAttribute":null,
      "Payload":{
        "QuestionText": "$A9QuestionText",
        "DefaultChoices":false,
        "DataExportTag":"TEST_A9",
        "QuestionType":"MC",
        "Selector":"SAVR",
        "SubSelector":"TX",
        "DataVisibility":{
            "Private":false,
            "Hidden":false
        },
        "Configuration":{
            "QuestionDescriptionOption":"UseText"
        },
        "Choices": $A9Choices,
        "ChoiceOrder": $A9ChoiceOrder,
        "Randomization":{
            "Advanced":null,
            "TotalRandSubset":"",
            "Type":"None"
        },
        "Validation":{
            "Settings":{
              "ForceResponse":"OFF",
              "ForceResponseType":"ON",
              "Type":"None"
            }
        },
        "RecodeValues": $A9RecodeValues,
        "GradingData":[
            {
              "ChoiceID":"$A9CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language":[

        ],
        "NextChoiceId":9,
        "NextAnswerId":1,
        "QuestionID":"QID84",
        "QuestionJS": ""
      }
    },
    {
      "SurveyID":"SV_eyerBD842srQPYO",
      "Element":"SQ",
      "PrimaryAttribute":"QID85",
      "SecondaryAttribute": "Question 10/10.",
      "TertiaryAttribute":null,
      "Payload":{
        "QuestionText": "$A10QuestionText",
        "DefaultChoices":false,
        "DataExportTag":"TEST_A10 ",
        "QuestionType":"MC",
        "Selector":"SAVR",
        "SubSelector":"TX",
        "DataVisibility":{
            "Private":false,
            "Hidden":false
        },
        "Configuration":{
            "QuestionDescriptionOption":"UseText"
        },
        "Choices": $A10Choices,
        "ChoiceOrder": $A10ChoiceOrder,
        "Randomization":{
            "Advanced":null,
            "TotalRandSubset":"",
            "Type":"None"
        },
        "Validation":{
            "Settings":{
              "ForceResponse":"OFF",
              "ForceResponseType":"ON",
              "Type":"None"
            }
        },
        "RecodeValues": $A10RecodeValues,
        "GradingData":[
            {
              "ChoiceID":"$A10CorrectChoiceID",
              "Grades":{
                  "SC_78JgOoF7SGSRmAe":"1"
              },
              "index":0
            }
        ],
        "Language":[

        ],
        "NextChoiceId":9,
        "NextAnswerId":1,
        "QuestionID":"QID85",
        "QuestionJS": ""
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "STAT",
      "PrimaryAttribute": "Survey Statistics",
      "SecondaryAttribute": null,
      "TertiaryAttribute": null,
      "Payload": {
        "MobileCompatible": true,
        "ID": "Survey Statistics"
      }
    },
    {
      "SurveyID": "SV_eP5ggSR1YMcI2HA",
      "Element": "TR",
      "PrimaryAttribute": "TR_4Ou4QGQDsjJLZ0a",
      "SecondaryAttribute": null,
      "TertiaryAttribute": null,
      "Payload": {
        "TriggerAction": "EmailMessage",
        "Type": "OnQuestionResponse",
        "ToEmail": "$${q://QID3/ChoiceTextEntryValue}",
        "FromName": "Computational Policy Lab",
        "FromEmail": "pingpongedu@hks.harvard.edu",
        "SendDate": "now",
        "Subject": "Assignment Submitted",
        "Message": "<div style=\"text-align: left;\"><span style=\"font-size:19px;\"><strong>You&#39;re all set!</strong></span><br />\n<br />\nYour second assignment was successfully submitted for $${e://Field/pp_class_name} on $${date://CurrentDate/FL} at $${date://CurrentTime/TL} ET. Your instructor will be notified so you can get credit for your assignment.<br />\n<br />\nIf you have any questions, please reach out to your instructor.</div>\n",
        "IncludeReport": false,
        "UseFullText": false,
        "Logic": {
          "0": {
            "0": {
              "LogicType": "Question",
              "QuestionID": "QID2",
              "QuestionIsInLoop": "no",
              "ChoiceLocator": "q://QID2/ChoiceTextEntryValue",
              "Operator": "NotEmpty",
              "QuestionIDFromLocator": "QID2",
              "LeftOperand": "q://QID2/ChoiceTextEntryValue",
              "Type": "Expression",
              "Description": "<span class=\"ConjDesc\">If</span> <span class=\"QuestionDesc\">Full Name</span> <span class=\"LeftOpDesc\">Text Response</span> <span class=\"OpDesc\">Is Not Empty</span> "
            },
            "Type": "If"
          },
          "Type": "BooleanExpression"
        },
        "ID": "TR_4Ou4QGQDsjJLZ0a"
      }
    }
  ]
}
""")
