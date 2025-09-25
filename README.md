# AI Weekly Planner

A minimal cross-platform desktop application that helps you plan your week. You can block out busy times, enter your weekly tasks and long-term goals, and let an AI scheduler (defaulting to the `gpt-5` OpenAI model) produce a conflict-aware plan. The app also shows pop-up reminders when it's time to work on a scheduled task.

## Features

- Visual weekly availability editor where you can click-and-drag (or click cells) to mark hours you're unavailable.
- Task and goal management panels with difficulty tagging and optional goal-task linking.
- AI-assisted schedule generation using the OpenAI Responses API. Scheduling requires a valid OpenAI API key.
- Conflict detection against existing busy slots.
- Day-by-day schedule breakdown that includes context from earlier days.
- Background reminder service that surfaces Tkinter pop-up notifications at the scheduled times.

## Requirements

- Python 3.9+
- Tkinter (bundled with Python on Windows/macOS).
- `openai` Python package and an OpenAI API key for AI scheduling.

Install dependencies (only `openai` is non-standard):

```bash
pip install openai
```

Set your OpenAI credentials:

```bash
export OPENAI_API_KEY="sk-your-key"
# Optionally select a specific model (defaults to gpt-5 for future compatibility)
export OPENAI_MODEL="gpt-4o"
```

## Running the App

```bash
python task_manager.py
```

On first launch each week:

1. Select **Weekly Availability** and click hours when you are busy (dark cells = unavailable).
2. Add your weekly tasks, including estimated duration, difficulty, and optional goal alignment.
3. Define overarching goals in the goals panel.
4. Click **Generate Schedule** to ask the AI to create a plan.
5. Review the proposed plan in the right-hand panel. Conflicts with busy slots will be highlighted via a warning dialog.
6. Click **Start Reminders** to enable pop-up alerts when it's time to focus on each block.

## Notes

- If the OpenAI API isn't configured, scheduling is unavailable until credentials are supplied.
- Generated reminders roll forward by a week if the scheduled time has already passed when reminders are started.
- The application deliberately avoids platform-specific notification APIs to remain portable between macOS and Windows; reminders are Tkinter windows that appear in the foreground.
