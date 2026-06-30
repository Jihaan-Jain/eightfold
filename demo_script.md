# 2-Minute Demo Walkthrough Script

*This script is written in a natural, conversational flow. The bracketed text `[like this]` tells you exactly what to do on screen, while the normal text is exactly what you should say out loud. Speak at a comfortable, confident pace.*

---

**[Action: Start with VS Code open, showing the project folder structure in the explorer panel on the left.]**

"Hi, this is my Multi-Source Candidate Data Transformer. 

The goal of this project is to take messy, conflicting candidate records from CSVs, ATS exports, and resumes, and resolve them into a single, canonical profile per person. 

As you can see, the repository is cleanly organized into source modules, configurations, and a comprehensive suite of over 1,200 tests."

**[Action: Switch to your terminal and type `python -m src.cli --help`, pressing Enter to show the output.]**

"The main entry point is this command-line interface. It's built for production, meaning it's fully configurable. You can pass in multiple data sources at once, and adjust things like the merge strategy or identity match thresholds right here at runtime."

**[Action: Open `sample_data/recruiter_sample.csv` in VS Code. Use your mouse to highlight row 4, which starts with `priya.sharma@gmail.com`.]**

"To see it in action, let's look at this sample data. Notice row four—it's a duplicate entry for Priya. It has no name, just her email and phone, plus a couple of extra skills. A naive system would create a messy duplicate profile. Let's see what our pipeline does."

**[Action: In the terminal, run the pipeline command: `python -m src.cli --csv sample_data/recruiter_sample.csv --ats sample_data/ats_sample.json --output sample_data/output_default.json`]**

"We'll run the pipeline... Five records go in, and four profiles come out."

**[Action: Open `sample_data/output_default.json` and scroll to Priya's profile. Highlight her `skills` array with your mouse.]**

"If we check the output for Priya, the system recognized the email match, merged the records, and successfully combined the skills from both rows. We now have all six skills in one place. Nothing was lost, and no duplicate was made."

**[Action: Open `src/merge/identity_resolver.py` and scroll to the hard signals block around line 200.]**

"The engineering decision I’m most proud of is here in the identity resolver. I deliberately chose to treat emails and phone numbers as hard identity signals, rather than just adding them to a weighted score. If two records share an exact email, it's definitive proof they are the same person. Treating it deterministically avoids false negatives and makes every single merge completely auditable."

**[Action: Open `tests/test_identity_resolver.py` and scroll down to the `test_transitivity_merges_three_records` test around line 224.]**

"I also designed this to handle complex edge cases, like transitivity. In this test, record A and B share an email, and B and C share a phone. Even though A and C have no direct overlap, my Union-Find implementation correctly groups all three together into a single profile."

**[Action: Open `configs/output_schemas/recruiter_view.yaml` on the left side of the screen, and `sample_data/output_recruiter_view.json` on the right side.]**

"Finally, the output schema is totally decoupled from the internal data model. Using a simple YAML config, like this recruiter view, I can rename fields and flatten nested objects into simple string lists at runtime, without touching a single line of Python code."

**[Action: Switch back to the terminal and run `python -m pytest tests/ -q`]**

"The entire pipeline is robust, modular, and backed by a fully green test suite. Thank you."

**[Action: Let the test suite finish running so the final `1263 passed` message sits on the screen, then stop the recording.]**
