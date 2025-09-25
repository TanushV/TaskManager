"""
Task Manager application using Tkinter and OpenAI GPT scheduling assistance.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - openai might not be installed during tests
    OpenAI = None  # type: ignore

import tkinter as tk
from tkinter import messagebox, ttk

WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


@dataclass
class Task:
    name: str
    duration_hours: float
    difficulty: str
    notes: str = ""
    goal: Optional[str] = None


@dataclass
class Goal:
    name: str
    difficulty: str
    notes: str = ""


@dataclass
class TimeBlock:
    title: str
    day: str
    start_time: str  # HH:MM format
    end_time: str
    details: str = ""

    def overlaps(self, other: "TimeBlock") -> bool:
        if self.day != other.day:
            return False
        start_a = datetime.strptime(self.start_time, "%H:%M")
        end_a = datetime.strptime(self.end_time, "%H:%M")
        start_b = datetime.strptime(other.start_time, "%H:%M")
        end_b = datetime.strptime(other.end_time, "%H:%M")
        return start_a < end_b and start_b < end_a


class GPTScheduler:
    """Wrapper around an OpenAI client that prompts GPT for weekly schedules."""

    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        self.client: Optional[OpenAI]
        if OpenAI is None or api_key is None:
            self.client = None
        else:
            self.client = OpenAI(api_key=api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-5")

    def is_available(self) -> bool:
        return self.client is not None

    def generate_schedule(self, context: Dict) -> Dict:
        if not self.is_available():
            raise RuntimeError("OpenAI client not available")

        instructions = (
            "You are an AI task scheduler. Generate a JSON object with a 'days' field. "
            "For each day in the upcoming week, provide an ordered list of focus blocks. "
            "Each block must include title, start, end (HH:MM 24h), and details. Reference the "
            "tasks and goals the block advances, and whenever possible bundle several related "
            "tasks (especially those tied to the same goal) into a single block rather than "
            "creating one block per task. Ensure you respect busy blocks and avoid conflicts."
        )
        prompt = json.dumps(context, indent=2)
        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": instructions,
                },
                {
                    "role": "user",
                    "content": f"Create a schedule for this week: {prompt}",
                },
            ],
            temperature=0.4,
            max_output_tokens=1500,
            response_format={"type": "json_object"},
        )
        content = response.output[0].content[0].text  # type: ignore[assignment]
        return json.loads(content)


class TaskManagerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AI Weekly Planner")
        self.geometry("1200x780")

        self.gpt = GPTScheduler()
        self.tasks: List[Task] = []
        self.goals: List[Goal] = []
        self.busy_slots: Dict[str, List[Tuple[int, int]]] = {day: [] for day in WEEKDAYS}
        self.generated_blocks: List[TimeBlock] = []
        self.reminder_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

        self._build_ui()

    # UI construction -----------------------------------------------------
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="nsew")

        availability_frame = ttk.Frame(notebook)
        notebook.add(availability_frame, text="Weekly Availability")
        self._build_availability_editor(availability_frame)

        planning_frame = ttk.Frame(notebook)
        notebook.add(planning_frame, text="Tasks & Goals")
        self._build_task_goal_editor(planning_frame)

        output_frame = ttk.Frame(self)
        output_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(1, weight=1)

        ttk.Label(output_frame, text="Generated Schedule", font=("Arial", 14, "bold")).grid(
            row=0, column=0, pady=(0, 5)
        )
        self.schedule_text = tk.Text(output_frame, wrap="word", state="disabled")
        self.schedule_text.grid(row=1, column=0, sticky="nsew")

        button_frame = ttk.Frame(output_frame)
        button_frame.grid(row=2, column=0, pady=10, sticky="ew")
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)

        self.generate_button = ttk.Button(
            button_frame, text="Generate Schedule", command=self.generate_schedule
        )
        self.generate_button.grid(row=0, column=0, padx=5, sticky="ew")

        self.start_reminders_button = ttk.Button(
            button_frame, text="Start Reminders", command=self.start_reminders, state="disabled"
        )
        self.start_reminders_button.grid(row=0, column=1, padx=5, sticky="ew")

    def _build_availability_editor(self, container: ttk.Frame) -> None:
        info = (
            "Click cells to toggle availability. Dark cells mean you're busy. "
            "Blocks are in 1-hour increments."
        )
        ttk.Label(container, text=info, wraplength=400).grid(row=0, column=0, columnspan=8, pady=5)

        self.availability_buttons: Dict[Tuple[str, int], tk.Button] = {}
        for col, day in enumerate(WEEKDAYS):
            ttk.Label(container, text=day).grid(row=1, column=col + 1)
        for row in range(24):
            hour_label = f"{row:02d}:00"
            ttk.Label(container, text=hour_label).grid(row=row + 2, column=0, padx=5)
            for col, day in enumerate(WEEKDAYS):
                btn = tk.Button(
                    container,
                    width=6,
                    relief=tk.RAISED,
                    command=lambda d=day, h=row: self.toggle_busy(d, h),
                    bg="white",
                )
                btn.grid(row=row + 2, column=col + 1, padx=1, pady=1)
                self.availability_buttons[(day, row)] = btn

    def _build_task_goal_editor(self, container: ttk.Frame) -> None:
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)

        # Tasks -------------------------------------------------------------
        task_frame = ttk.LabelFrame(container, text="Weekly Tasks")
        task_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        ttk.Label(task_frame, text="Task Name").grid(row=0, column=0, sticky="w")
        self.task_name_var = tk.StringVar()
        ttk.Entry(task_frame, textvariable=self.task_name_var).grid(row=0, column=1, sticky="ew")

        ttk.Label(task_frame, text="Duration (hours)").grid(row=1, column=0, sticky="w")
        self.task_duration_var = tk.StringVar()
        ttk.Entry(task_frame, textvariable=self.task_duration_var).grid(row=1, column=1, sticky="ew")

        ttk.Label(task_frame, text="Difficulty").grid(row=2, column=0, sticky="w")
        self.task_difficulty_var = tk.StringVar(value="Medium")
        ttk.Combobox(
            task_frame,
            textvariable=self.task_difficulty_var,
            values=["Low", "Medium", "High"],
            state="readonly",
        ).grid(row=2, column=1, sticky="ew")

        ttk.Label(task_frame, text="Related Goal (optional)").grid(row=3, column=0, sticky="w")
        self.task_goal_var = tk.StringVar()
        self.task_goal_combo = ttk.Combobox(task_frame, textvariable=self.task_goal_var)
        self.task_goal_combo.grid(row=3, column=1, sticky="ew")

        ttk.Label(task_frame, text="Notes").grid(row=4, column=0, sticky="w")
        self.task_notes_var = tk.StringVar()
        ttk.Entry(task_frame, textvariable=self.task_notes_var).grid(row=4, column=1, sticky="ew")

        ttk.Button(task_frame, text="Add Task", command=self.add_task).grid(
            row=5, column=0, columnspan=2, pady=5, sticky="ew"
        )

        self.task_listbox = tk.Listbox(task_frame, height=12)
        self.task_listbox.grid(row=6, column=0, columnspan=2, sticky="nsew")
        task_frame.rowconfigure(6, weight=1)

        # Goals -------------------------------------------------------------
        goal_frame = ttk.LabelFrame(container, text="Long-Term Goals")
        goal_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        ttk.Label(goal_frame, text="Goal Name").grid(row=0, column=0, sticky="w")
        self.goal_name_var = tk.StringVar()
        ttk.Entry(goal_frame, textvariable=self.goal_name_var).grid(row=0, column=1, sticky="ew")

        ttk.Label(goal_frame, text="Difficulty").grid(row=1, column=0, sticky="w")
        self.goal_difficulty_var = tk.StringVar(value="Medium")
        ttk.Combobox(
            goal_frame,
            textvariable=self.goal_difficulty_var,
            values=["Low", "Medium", "High"],
            state="readonly",
        ).grid(row=1, column=1, sticky="ew")

        ttk.Label(goal_frame, text="Notes").grid(row=2, column=0, sticky="w")
        self.goal_notes_var = tk.StringVar()
        ttk.Entry(goal_frame, textvariable=self.goal_notes_var).grid(row=2, column=1, sticky="ew")

        ttk.Button(goal_frame, text="Add Goal", command=self.add_goal).grid(
            row=3, column=0, columnspan=2, pady=5, sticky="ew"
        )

        self.goal_listbox = tk.Listbox(goal_frame, height=12)
        self.goal_listbox.grid(row=4, column=0, columnspan=2, sticky="nsew")
        goal_frame.rowconfigure(4, weight=1)

    # Availability editing ------------------------------------------------
    def toggle_busy(self, day: str, hour: int) -> None:
        slot = (day, hour)
        btn = self.availability_buttons[slot]
        busy_list = self.busy_slots[day]

        if hour in [h for h, _ in busy_list]:
            busy_list[:] = [(h, dur) for h, dur in busy_list if h != hour]
            btn.configure(bg="white", relief=tk.RAISED)
        else:
            busy_list.append((hour, 1))  # store duration=1 hour for grid simplicity
            btn.configure(bg="#444", relief=tk.SUNKEN)

    # Task & goal management ---------------------------------------------
    def refresh_task_goal_links(self) -> None:
        goal_names = [goal.name for goal in self.goals]
        self.task_goal_combo.configure(values=["None"] + goal_names)

    def add_task(self) -> None:
        name = self.task_name_var.get().strip()
        duration_str = self.task_duration_var.get().strip()
        difficulty = self.task_difficulty_var.get()
        goal_name = self.task_goal_var.get().strip()
        notes = self.task_notes_var.get().strip()

        if not name or not duration_str:
            messagebox.showwarning("Missing information", "Task name and duration are required.")
            return
        try:
            duration = float(duration_str)
        except ValueError:
            messagebox.showerror("Invalid duration", "Duration must be a number.")
            return

        goal = goal_name if goal_name and goal_name != "None" else None
        task = Task(name=name, duration_hours=duration, difficulty=difficulty, notes=notes, goal=goal)
        self.tasks.append(task)
        self.task_listbox.insert(tk.END, f"{name} ({duration}h, {difficulty})")
        self.task_name_var.set("")
        self.task_duration_var.set("")
        self.task_notes_var.set("")

    def add_goal(self) -> None:
        name = self.goal_name_var.get().strip()
        difficulty = self.goal_difficulty_var.get()
        notes = self.goal_notes_var.get().strip()

        if not name:
            messagebox.showwarning("Missing information", "Goal name is required.")
            return

        goal = Goal(name=name, difficulty=difficulty, notes=notes)
        self.goals.append(goal)
        self.goal_listbox.insert(tk.END, f"{name} ({difficulty})")
        self.goal_name_var.set("")
        self.goal_notes_var.set("")
        self.refresh_task_goal_links()

    # Schedule generation -------------------------------------------------
    def generate_schedule(self) -> None:
        if not self.tasks:
            messagebox.showwarning("No tasks", "Add at least one task before generating a schedule.")
            return

        if not self.gpt.is_available():
            messagebox.showerror(
                "OpenAI unavailable",
                "An OpenAI API key is required. Set OPENAI_API_KEY in your environment to enable scheduling.",
            )
            return

        context = self._build_schedule_context()

        try:
            schedule = self.gpt.generate_schedule(context)
        except Exception as exc:
            messagebox.showerror("Scheduling failed", str(exc))
            return

        blocks = self._parse_schedule(schedule)
        conflicts = self._find_conflicts(blocks)
        if conflicts:
            conflict_text = "\n".join(conflicts)
            messagebox.showwarning("Conflicts detected", conflict_text)

        self.generated_blocks = blocks
        self._display_schedule(blocks)
        self.start_reminders_button.configure(state="normal")

    def _build_schedule_context(self) -> Dict:
        busy = self._build_busy_context()
        tasks = [task.__dict__ for task in self.tasks]
        goals = [goal.__dict__ for goal in self.goals]

        tasks_by_goal: Dict[str, List[Dict[str, str]]] = {}
        goal_lookup = {goal.name: goal for goal in self.goals}
        for task in self.tasks:
            key = task.goal if task.goal else "Unaligned"
            tasks_by_goal.setdefault(key, []).append(
                {
                    "name": task.name,
                    "duration_hours": task.duration_hours,
                    "difficulty": task.difficulty,
                    "notes": task.notes,
                }
            )

        goal_summaries = []
        for name, goal in goal_lookup.items():
            goal_summaries.append(
                {
                    "goal": name,
                    "difficulty": goal.difficulty,
                    "notes": goal.notes,
                    "tasks": tasks_by_goal.get(name, []),
                }
            )
        if "Unaligned" in tasks_by_goal:
            goal_summaries.append({"goal": "Unaligned", "difficulty": "", "notes": "", "tasks": tasks_by_goal["Unaligned"]})

        context = {
            "goals": goals,
            "tasks": tasks,
            "busy": busy,
            "goal_focus": goal_summaries,
            "guidelines": {
                "bundle_tasks": "Group related tasks into shared focus blocks when possible.",
                "balance": "Balance workload across the week and mix easy and difficult sessions.",
                "avoid_single_task_blocks": "Avoid mapping each task to its own block unless necessary.",
            },
        }
        return context

    def _build_busy_context(self) -> Dict[str, List[Dict[str, str]]]:
        busy_context: Dict[str, List[Dict[str, str]]] = {day: [] for day in WEEKDAYS}
        for day, slots in self.busy_slots.items():
            for hour, duration in slots:
                start = f"{hour:02d}:00"
                end_hour = hour + duration
                end = f"{end_hour:02d}:00"
                busy_context[day].append({"start": start, "end": end, "title": "Busy"})
        return busy_context

    def _parse_schedule(self, schedule: Dict) -> List[TimeBlock]:
        blocks: List[TimeBlock] = []
        days = schedule.get("days", {})
        for day, entries in days.items():
            if day not in WEEKDAYS:
                continue
            for entry in entries:
                try:
                    block = TimeBlock(
                        title=entry["title"],
                        day=day,
                        start_time=entry["start"],
                        end_time=entry["end"],
                        details=entry.get("details", ""),
                    )
                    blocks.append(block)
                except KeyError:
                    continue
        return sorted(blocks, key=lambda b: (WEEKDAYS.index(b.day), b.start_time))

    def _find_conflicts(self, blocks: List[TimeBlock]) -> List[str]:
        messages: List[str] = []
        busy_blocks = [
            TimeBlock(title="Busy", day=day, start_time=slot["start"], end_time=slot["end"])
            for day, slots in self._build_busy_context().items()
            for slot in slots
        ]

        for block in blocks:
            for busy in busy_blocks:
                if block.overlaps(busy):
                    messages.append(
                        f"{block.title} on {block.day} {block.start_time}-{block.end_time} overlaps busy time."
                    )
        return messages

    def _display_schedule(self, blocks: List[TimeBlock]) -> None:
        grouped: Dict[str, List[TimeBlock]] = {day: [] for day in WEEKDAYS}
        for block in blocks:
            grouped[block.day].append(block)

        lines: List[str] = []
        for day in WEEKDAYS:
            lines.append(day)
            lines.append("-" * len(day))
            context_lines = self._day_context(day, grouped[day])
            lines.extend(context_lines)
            lines.append("")

        text = "\n".join(lines)
        self.schedule_text.configure(state="normal")
        self.schedule_text.delete("1.0", tk.END)
        self.schedule_text.insert(tk.END, text)
        self.schedule_text.configure(state="disabled")

    def _day_context(self, day: str, blocks: List[TimeBlock]) -> List[str]:
        lines: List[str] = []
        busy_slots = self._build_busy_context()[day]
        if busy_slots:
            lines.append("Existing commitments:")
            for slot in busy_slots:
                lines.append(f"  {slot['start']}-{slot['end']}: {slot['title']}")
        else:
            lines.append("Existing commitments: None")

        if blocks:
            lines.append("Planned tasks:")
            for block in blocks:
                lines.append(
                    f"  {block.start_time}-{block.end_time}: {block.title} ({block.details})"
                )
        else:
            lines.append("Planned tasks: None")
        return lines

    # Reminder handling ---------------------------------------------------
    def start_reminders(self) -> None:
        if not self.generated_blocks:
            messagebox.showwarning("No schedule", "Generate a schedule first.")
            return

        if self.reminder_thread and self.reminder_thread.is_alive():
            messagebox.showinfo("Reminders running", "Reminders are already active.")
            return

        self.stop_event.clear()
        self.reminder_thread = threading.Thread(target=self._reminder_loop, daemon=True)
        self.reminder_thread.start()
        self.start_reminders_button.configure(state="disabled")
        messagebox.showinfo("Reminders started", "Pop-up reminders will appear at the scheduled times.")

    def _reminder_loop(self) -> None:
        blocks_by_datetime: List[Tuple[datetime, TimeBlock]] = []
        now = datetime.now()
        monday = now - timedelta(days=now.weekday())

        for block in self.generated_blocks:
            day_index = WEEKDAYS.index(block.day)
            block_date = monday + timedelta(days=day_index)
            start_hour, start_minute = map(int, block.start_time.split(":"))
            block_dt = block_date.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
            if block_dt < now:
                block_dt += timedelta(weeks=1)
            blocks_by_datetime.append((block_dt, block))

        shown: set = set()
        while not self.stop_event.is_set():
            current = datetime.now()
            for block_dt, block in blocks_by_datetime:
                if block_dt <= current < block_dt + timedelta(minutes=1):
                    identifier = (block.day, block.start_time, block.title)
                    if identifier not in shown:
                        self.after(0, self._show_reminder, block)
                        shown.add(identifier)
            time.sleep(30)

    def _show_reminder(self, block: TimeBlock) -> None:
        popup = tk.Toplevel(self)
        popup.title("Task Reminder")
        popup.geometry("320x180")
        ttk.Label(popup, text=f"{block.title}", font=("Arial", 14, "bold")).pack(pady=10)
        ttk.Label(
            popup,
            text=f"{block.day} {block.start_time}-{block.end_time}\n{block.details}",
            wraplength=280,
            justify="center",
        ).pack(pady=10)
        ttk.Button(popup, text="Done", command=popup.destroy).pack(pady=10)

    def on_close(self) -> None:
        self.stop_event.set()
        self.destroy()


def main() -> None:
    app = TaskManagerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
