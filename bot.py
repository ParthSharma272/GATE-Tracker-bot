# bot.py

import os
import json
import random
import logging
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from apscheduler.schedulers.background import BackgroundScheduler

from quotes import QUOTES

# --- Configuration & Setup ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATA_FILE = "data.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Data Handling ---
def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "milestones": [], 
            "daily_targets": {}, 
            "reminders": {},
            "subjects": {},  # {subject_name: {topics: [], description: ""}}
            "user_progress": {}  # {user_id: {subject_name: {completed_topics: [], completion_date: ""}}}
        }

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- Helper Functions ---
def get_random_quote():
    quote, author = random.choice(QUOTES)
    return f'"{quote}" - {author}'

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if update.effective_chat.type == 'private':
        return True
    admins = await context.bot.get_chat_administrators(chat_id)
    return any(admin.user.id == user_id for admin in admins)

async def show_user_targets_for_date(update: Update, user_id: str, user_name: str, date_str: str):
    """Helper function to display user's targets for a specific date"""
    # Handle cases where update.message might be None
    if not update.message:
        return
        
    data = load_data()
    
    if (date_str not in data.get("daily_targets", {}) or 
        user_id not in data["daily_targets"][date_str]):
        if date_str == datetime.now().strftime("%Y-%m-%d"):
            await update.message.reply_text("You don't have any targets set for today. Use `/today <goal>` to set one!")
        else:
            await update.message.reply_text(f"You don't have any targets set for {date_str}. Use `/set_date_target {date_str} <goal>` to set one!")
        return
    
    user_targets = data["daily_targets"][date_str][user_id]
    targets = user_targets.get("targets", [])
    
    # Handle old format conversion
    if targets and isinstance(targets[0], str):
        # Convert old format to new format
        new_targets = []
        for target in targets:
            new_targets.append({"text": target, "completed": False, "completed_at": None})
        user_targets["targets"] = new_targets
        save_data(data)
        targets = new_targets
    
    date_display = "Today" if date_str == datetime.now().strftime("%Y-%m-%d") else date_str
    message = f"🎯 **Your Targets for {date_display}** 🎯\n\n"
    
    completed_count = 0
    for i, target_obj in enumerate(targets, 1):
        if target_obj["completed"]:
            message += f"✅ **{i}.** ~~{target_obj['text']}~~\n"
            completed_count += 1
        else:
            message += f"⭕ **{i}.** {target_obj['text']}\n"
    
    progress_percent = (completed_count / len(targets)) * 100 if targets else 0
    message += f"\n📊 **Progress:** {completed_count}/{len(targets)} ({progress_percent:.0f}%) completed\n"
    
    message += f"\n💡 Use `/complete_goal {date_str} <number>` to mark as done\n"
    message += f"💡 Use `/edit_target <number> <new_goal>` to edit\n"
    message += f"💡 Use `/delete_target <number>` to delete"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def set_date_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /set_date_target YYYY-MM-DD <your goal>\n\nExample: `/set_date_target 2025-08-10 Complete chapter 5`")
        return
    
    try:
        date_str = context.args[0]
        # Validate date format
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("Please use the correct date format: YYYY-MM-DD (e.g., 2025-08-10)")
        return
    
    target = " ".join(context.args[1:])
    
    data = load_data()
    if date_str not in data["daily_targets"]:
        data["daily_targets"][date_str] = {}
    
    if user_id not in data["daily_targets"][date_str]:
        data["daily_targets"][date_str][user_id] = {"name": user_name, "targets": []}
    
    # Handle data migration from old format to new format
    user_data = data["daily_targets"][date_str][user_id]
    if "targets" not in user_data:
        # Migrate from old format
        if "target" in user_data:
            # Convert old single target or list of strings to new format
            old_targets = user_data["target"]
            if isinstance(old_targets, str):
                # Single target (very old format)
                new_targets = [{"text": old_targets, "completed": False, "completed_at": None}]
            elif isinstance(old_targets, list):
                # List of strings (old format)
                new_targets = []
                for target in old_targets:
                    if isinstance(target, str):
                        new_targets.append({"text": target, "completed": False, "completed_at": None})
                    else:
                        new_targets.append(target)  # Already in new format
            else:
                new_targets = []
            user_data["targets"] = new_targets
            del user_data["target"]  # Remove old key
        else:
            # No targets at all, create empty list
            user_data["targets"] = []
    
    # Add the new target with completion status
    target_obj = {"text": target, "completed": False, "completed_at": None}
    data["daily_targets"][date_str][user_id]["targets"].append(target_obj)
    save_data(data)
    
    target_count = len(data["daily_targets"][date_str][user_id]["targets"])
    await update.message.reply_text(f"✅ Target {target_count} set for {date_str}. Lock and load!")

async def complete_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /complete_goal YYYY-MM-DD <target_number>\n\nExample: `/complete_goal 2025-08-03 1` to complete your first target for that date\nOr use: `/complete_goal today 1` for today's targets")
        return
    
    date_input = context.args[0]
    if date_input.lower() == "today":
        date_str = datetime.now().strftime("%Y-%m-%d")
    else:
        try:
            # Validate date format
            datetime.strptime(date_input, "%Y-%m-%d")
            date_str = date_input
        except ValueError:
            await update.message.reply_text("Please use the correct date format: YYYY-MM-DD or 'today'")
            return
    
    try:
        target_number = int(context.args[1])
        if target_number < 1:
            raise ValueError("Target number must be positive")
    except ValueError:
        await update.message.reply_text("Please provide a valid target number (1, 2, 3, etc.)")
        return
    
    data = load_data()
    
    if (date_str not in data.get("daily_targets", {}) or 
        user_id not in data["daily_targets"][date_str]):
        await update.message.reply_text(f"You don't have any targets set for {date_str}.")
        return
    
    user_targets = data["daily_targets"][date_str][user_id]
    targets = user_targets.get("targets", [])
    
    # Handle old format conversion
    if targets and isinstance(targets[0], str):
        # Convert old format to new format
        new_targets = []
        for target in targets:
            new_targets.append({"text": target, "completed": False, "completed_at": None})
        user_targets["targets"] = new_targets
        save_data(data)
        targets = new_targets
    
    if target_number > len(targets):
        await update.message.reply_text(f"You only have {len(targets)} target(s) for {date_str}. Cannot complete target #{target_number}.")
        return
    
    target_obj = targets[target_number - 1]
    
    if target_obj["completed"]:
        await update.message.reply_text(f"Target #{target_number} is already completed: _{target_obj['text']}_")
        return
    
    # Mark as completed
    target_obj["completed"] = True
    target_obj["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    save_data(data)
    
    # Calculate progress
    completed_count = sum(1 for t in targets if t["completed"])
    total_count = len(targets)
    progress_percent = (completed_count / total_count) * 100
    
    date_display = "today" if date_str == datetime.now().strftime("%Y-%m-%d") else date_str
    await update.message.reply_text(f"🎉 Target #{target_number} completed for {date_display}!\n\n✅ _{target_obj['text']}_\n\n📊 Progress: {completed_count}/{total_count} ({progress_percent:.0f}%) completed\n\n{get_random_quote()}")

# --- Admin Commands ---
async def set_milestone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this command.")
        return

    try:
        parts = context.args
        date_str = parts[0]
        description = " ".join(parts[1:]).strip('"')
        deadline = datetime.strptime(date_str, "%Y-%m-%d")

        data = load_data()
        data["milestones"].append({"date": date_str, "description": description})
        data["milestones"].sort(key=lambda x: x["date"])
        save_data(data)
        
        await update.message.reply_text(f"✅ Milestone set for {date_str}: {description}")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /set_milestone YYYY-MM-DD \"Description\"")

async def edit_milestone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this command.")
        return

    try:
        m_num_str, field, new_value = context.args[0], context.args[1].lower(), " ".join(context.args[2:])
        m_num = int(m_num_str) - 1

        data = load_data()
        if not (0 <= m_num < len(data["milestones"])):
            await update.message.reply_text("Invalid milestone number.")
            return

        if field == "date":
            datetime.strptime(new_value, "%Y-%m-%d") # Validate date format
            data["milestones"][m_num]["date"] = new_value
            data["milestones"].sort(key=lambda x: x["date"])
        elif field == "description":
            data["milestones"][m_num]["description"] = new_value.strip('"')
        else:
            raise ValueError("Invalid field")
        
        save_data(data)
        await update.message.reply_text(f"✅ Milestone {m_num + 1} updated.")

    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /edit_milestone <number> <date|description> <new_value>")


async def view_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["milestones"]:
        await update.message.reply_text("No plan set yet. Use /set_milestone to create one.")
        return

    message = "🗓️ **Our Group's Prep Plan** 🗓️\n\n"
    today = datetime.now()
    for i, ms in enumerate(data["milestones"]):
        deadline = datetime.strptime(ms["date"], "%Y-%m-%d")
        days_left = (deadline - today).days
        message += f"🎯 **Milestone {i+1}:** {ms['description']}\n"
        message += f"   -> **Deadline:** {ms['date']} ({days_left} days left)\n\n"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def clear_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this command.")
        return
    data = load_data()
    data["milestones"] = []
    save_data(data)
    await update.message.reply_text("🗑️ The entire plan has been cleared.")

async def delete_milestone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this command.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /delete_milestone <milestone_number>\n\nExample: `/delete_milestone 2` to delete the 2nd milestone")
        return
    
    try:
        milestone_number = int(context.args[0])
        if milestone_number < 1:
            raise ValueError("Milestone number must be positive")
    except ValueError:
        await update.message.reply_text("Please provide a valid milestone number (1, 2, 3, etc.)")
        return
    
    data = load_data()
    if not data["milestones"]:
        await update.message.reply_text("No milestones exist to delete. Use /view_plan to see current milestones.")
        return
    
    if milestone_number > len(data["milestones"]):
        await update.message.reply_text(f"Only {len(data['milestones'])} milestone(s) exist. Cannot delete milestone #{milestone_number}.")
        return
    
    # Delete the milestone
    deleted_milestone = data["milestones"].pop(milestone_number - 1)
    save_data(data)
    
    await update.message.reply_text(f"🗑️ Milestone #{milestone_number} deleted:\n\n📅 **{deleted_milestone['date']}**\n📝 {deleted_milestone['description']}\n\nRemaining milestones: {len(data['milestones'])}")

async def delete_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this command.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /delete_topic \"Subject Name\" \"Topic Name\"\n\nExample: `/delete_topic \"Mathematics\" \"Linear Algebra\"` to delete that specific topic")
        return
    
    subject_name = context.args[0].strip('"')
    topic_name = " ".join(context.args[1:]).strip('"')
    
    data = load_data()
    if "subjects" not in data or subject_name not in data["subjects"]:
        await update.message.reply_text(f"Subject '{subject_name}' not found. Use /view_subjects to see all available subjects.")
        return
    
    if topic_name not in data["subjects"][subject_name]["topics"]:
        await update.message.reply_text(f"Topic '{topic_name}' not found in subject '{subject_name}'. Use `/view_topics \"{subject_name}\"` to see all topics.")
        return
    
    # Remove the topic
    data["subjects"][subject_name]["topics"].remove(topic_name)
    data["subjects"][subject_name]["total_topics"] = len(data["subjects"][subject_name]["topics"])
    
    # Also remove from user progress
    removed_from_users = []
    if "user_progress" in data:
        for user_id in data["user_progress"]:
            if subject_name in data["user_progress"][user_id]:
                user_completed = data["user_progress"][user_id][subject_name]["completed_topics"]
                if topic_name in user_completed:
                    user_completed.remove(topic_name)
                    user_name = data["user_progress"][user_id].get("name", "Unknown User")
                    removed_from_users.append(user_name)
    
    save_data(data)
    
    message = f"🗑️ Topic '{topic_name}' deleted from subject '{subject_name}'\n\n"
    message += f"📚 Remaining topics in {subject_name}: {data['subjects'][subject_name]['total_topics']}\n"
    
    if removed_from_users:
        message += f"\n👥 Progress removed for {len(removed_from_users)} user(s): {', '.join(removed_from_users)}"
    
    await update.message.reply_text(message)

async def add_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this command.")
        return

    try:
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /add_subject \"Subject Name\" topic1,topic2,topic3")
            return
            
        subject_name = context.args[0].strip('"')
        topics_str = " ".join(context.args[1:])
        topics = [topic.strip() for topic in topics_str.split(',')]
        
        data = load_data()
        if "subjects" not in data:
            data["subjects"] = {}
            
        data["subjects"][subject_name] = {
            "topics": topics,
            "total_topics": len(topics)
        }
        save_data(data)
        
        await update.message.reply_text(f"✅ Subject '{subject_name}' added with {len(topics)} topics:\n• " + "\n• ".join(topics))
    except Exception as e:
        await update.message.reply_text("Usage: /add_subject \"Subject Name\" topic1,topic2,topic3")

async def delete_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this command.")
        return

    try:
        if len(context.args) < 1:
            await update.message.reply_text("Usage: /delete_subject \"Subject Name\"")
            return
            
        subject_name = context.args[0].strip('"')
        
        data = load_data()
        if "subjects" not in data or subject_name not in data["subjects"]:
            await update.message.reply_text(f"Subject '{subject_name}' not found.")
            return
        
        # Remove the subject
        del data["subjects"][subject_name]
        
        # Also remove user progress for this subject
        if "user_progress" in data:
            for user_id in data["user_progress"]:
                if subject_name in data["user_progress"][user_id]:
                    del data["user_progress"][user_id][subject_name]
        
        save_data(data)
        
        await update.message.reply_text(f"🗑️ Subject '{subject_name}' and all related progress data has been deleted.")
    except Exception as e:
        await update.message.reply_text("Usage: /delete_subject \"Subject Name\"")

async def view_subjects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if "subjects" not in data or not data["subjects"]:
        await update.message.reply_text("No GATE syllabus subjects defined yet. Admins can use /add_subject to add syllabus topics.")
        return
    
    message = "📚 **GATE Syllabus Subjects** 📚\n\n"
    for i, (subject, info) in enumerate(data["subjects"].items(), 1):
        message += f"**{i}. {subject}**\n"
        message += f"   📝 {info['total_topics']} syllabus topics\n"
        message += f"   Topics: {', '.join(info['topics'][:3])}{'...' if len(info['topics']) > 3 else ''}\n\n"
    
    message += "💡 Use `/complete \"Subject\" \"Topic\"` to mark syllabus topics as completed\n"
    message += "💡 Use `/today <goal>` to set personal daily targets (separate from syllabus)"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def view_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /view_topics \"Subject Name\"\n\nExample: `/view_topics \"Mathematics\"` to see all topics in Mathematics")
        return
    
    subject_name = " ".join(context.args).strip('"')
    
    data = load_data()
    if "subjects" not in data or subject_name not in data["subjects"]:
        await update.message.reply_text(f"Subject '{subject_name}' not found. Use /view_subjects to see all available subjects.")
        return
    
    subject_info = data["subjects"][subject_name]
    topics = subject_info["topics"]
    
    message = f"📝 **Topics in {subject_name}** 📝\n\n"
    message += f"**Total Topics:** {len(topics)}\n\n"
    
    # Show topics in numbered list
    for i, topic in enumerate(topics, 1):
        message += f"**{i}.** {topic}\n"
    
    # Show user's progress if available
    user_id = str(update.effective_user.id)
    if ("user_progress" in data and user_id in data["user_progress"] and 
        subject_name in data["user_progress"][user_id]):
        completed_topics = data["user_progress"][user_id][subject_name]["completed_topics"]
        completed_count = len(completed_topics)
        progress_percent = (completed_count / len(topics)) * 100
        
        message += f"\n📊 **Your Progress:** {completed_count}/{len(topics)} ({progress_percent:.1f}%) completed\n"
        
        if completed_topics:
            message += f"\n✅ **Completed Topics:**\n"
            for topic in completed_topics:
                message += f"• {topic}\n"
        
        remaining_topics = [t for t in topics if t not in completed_topics]
        if remaining_topics:
            message += f"\n⭕ **Remaining Topics:**\n"
            for topic in remaining_topics[:5]:  # Show first 5 remaining
                message += f"• {topic}\n"
            if len(remaining_topics) > 5:
                message += f"• ... and {len(remaining_topics) - 5} more\n"
    
    message += f"\n💡 Use `/complete \"{subject_name}\" \"Topic Name\"` to mark topics as completed"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def edit_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this command.")
        return
    
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /edit_topics \"Subject Name\" <add|remove|replace> <topics>\n\n"
            "Examples:\n"
            "• `/edit_topics \"Mathematics\" add \"New Topic 1,New Topic 2\"` - Add new topics\n"
            "• `/edit_topics \"Mathematics\" remove \"Topic to Remove\"` - Remove a topic\n"
            "• `/edit_topics \"Mathematics\" replace \"topic1,topic2,topic3\"` - Replace all topics"
        )
        return
    
    subject_name = context.args[0].strip('"')
    action = context.args[1].lower()
    topics_input = " ".join(context.args[2:]).strip('"')
    
    data = load_data()
    if "subjects" not in data or subject_name not in data["subjects"]:
        await update.message.reply_text(f"Subject '{subject_name}' not found. Use /view_subjects to see all available subjects.")
        return
    
    current_topics = data["subjects"][subject_name]["topics"]
    
    if action == "add":
        new_topics = [topic.strip() for topic in topics_input.split(',')]
        # Filter out topics that already exist
        unique_new_topics = [topic for topic in new_topics if topic not in current_topics]
        
        if not unique_new_topics:
            await update.message.reply_text("All specified topics already exist in this subject.")
            return
        
        current_topics.extend(unique_new_topics)
        data["subjects"][subject_name]["total_topics"] = len(current_topics)
        
        await update.message.reply_text(f"✅ Added {len(unique_new_topics)} new topic(s) to '{subject_name}':\n• " + "\n• ".join(unique_new_topics))
    
    elif action == "remove":
        topic_to_remove = topics_input
        
        if topic_to_remove not in current_topics:
            await update.message.reply_text(f"Topic '{topic_to_remove}' not found in subject '{subject_name}'.")
            return
        
        current_topics.remove(topic_to_remove)
        data["subjects"][subject_name]["total_topics"] = len(current_topics)
        
        # Also remove from user progress
        if "user_progress" in data:
            for user_id in data["user_progress"]:
                if subject_name in data["user_progress"][user_id]:
                    user_completed = data["user_progress"][user_id][subject_name]["completed_topics"]
                    if topic_to_remove in user_completed:
                        user_completed.remove(topic_to_remove)
        
        await update.message.reply_text(f"🗑️ Removed topic '{topic_to_remove}' from '{subject_name}' and all user progress.")
    
    elif action == "replace":
        new_topics = [topic.strip() for topic in topics_input.split(',')]
        old_count = len(current_topics)
        
        # Get topics that will be removed
        removed_topics = [topic for topic in current_topics if topic not in new_topics]
        
        # Update the subject
        data["subjects"][subject_name]["topics"] = new_topics
        data["subjects"][subject_name]["total_topics"] = len(new_topics)
        
        # Clean up user progress for removed topics
        if removed_topics and "user_progress" in data:
            for user_id in data["user_progress"]:
                if subject_name in data["user_progress"][user_id]:
                    user_completed = data["user_progress"][user_id][subject_name]["completed_topics"]
                    # Remove completed topics that no longer exist
                    data["user_progress"][user_id][subject_name]["completed_topics"] = [
                        topic for topic in user_completed if topic in new_topics
                    ]
        
        await update.message.reply_text(
            f"🔄 Replaced all topics in '{subject_name}':\n"
            f"• **Old count:** {old_count} topics\n"
            f"• **New count:** {len(new_topics)} topics\n"
            f"• **Removed:** {len(removed_topics)} topics\n"
            f"• **Added:** {len([t for t in new_topics if t not in current_topics])} topics"
        )
    
    else:
        await update.message.reply_text("Invalid action. Use 'add', 'remove', or 'replace'.")
        return
    
    save_data(data)

# --- Reminder Commands ---
async def daily_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    data = load_data()
    
    if not data["milestones"]: return

    today = datetime.now()
    next_deadline = None
    for ms in data["milestones"]:
        deadline_date = datetime.strptime(ms["date"], "%Y-%m-%d")
        if deadline_date > today:
            next_deadline = ms
            break

    if not next_deadline: return

    deadline_date = datetime.strptime(next_deadline["date"], "%Y-%m-%d")
    days_left = (deadline_date - today).days

    message = f"{get_random_quote()}\n---\n"
    message += "**Time to execute. ☀️**\n\n"
    message += f"🗓️ **{days_left} days** remain until your next deadline:\n"
    message += f"🎯 *{next_deadline['description']}*\n\n"
    message += "What will you conquer today?\nSet your target with the /today command."

    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN)


async def set_daily_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this command.")
        return

    chat_id = update.message.chat_id
    try:
        time_str = context.args[0]
        hour, minute = map(int, time_str.split(':'))
        
        # Remove existing job before starting a new one
        if 'job' in context.chat_data:
            context.chat_data['job'].schedule_removal()

        job = context.job_queue.run_daily(daily_reminder_job, time=datetime(1,1,1,hour,minute).time(), chat_id=chat_id)
        context.chat_data['job'] = job
        
        await update.message.reply_text(f"✅ Daily reminder set for {time_str} every day.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /set_daily_reminder HH:MM (e.g., 07:00)")

async def stop_daily_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this command.")
        return
        
    if 'job' not in context.chat_data:
        await update.message.reply_text("No active reminder to stop.")
        return
        
    context.chat_data['job'].schedule_removal()
    del context.chat_data['job']
    await update.message.reply_text("🛑 Daily reminder stopped.")

async def schedule_command_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    job_data = context.job.data
    command = job_data['command']
    message = job_data.get('message', '')
    
    if command == 'view_today':
        # Simulate the view_today command
        data = load_data()
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        if (today_str not in data.get("daily_targets", {}) or 
            not data["daily_targets"][today_str]):
            msg = "No daily targets set for today yet. Be the first with `/today <your goal>`!"
        else:
            msg = "🎯 **Today's Warriors & Their Targets** 🎯\n\n"
            
            for i, (user_id, user_data) in enumerate(data["daily_targets"][today_str].items(), 1):
                user_name = user_data.get("name", "Unknown User")
                targets = user_data.get("targets", user_data.get("target", []))
                
                # Handle old format conversion
                if targets and isinstance(targets[0], str):
                    new_targets = []
                    for target in targets:
                        new_targets.append({"text": target, "completed": False, "completed_at": None})
                    user_data["targets"] = new_targets
                    targets = new_targets
                    if "target" in user_data:
                        del user_data["target"]
                
                msg += f"**{i}) {user_name}**\n"
                completed_count = 0
                for j, target_obj in enumerate(targets, 1):
                    if isinstance(target_obj, dict):
                        if target_obj["completed"]:
                            msg += f"   ✅ ~~{target_obj['text']}~~\n"
                            completed_count += 1
                        else:
                            msg += f"   ⭕ {target_obj['text']}\n"
                    else:
                        # Handle any remaining old format
                        msg += f"   ⭕ {target_obj}\n"
                
                if targets:
                    progress_percent = (completed_count / len(targets)) * 100
                    msg += f"   📊 {completed_count}/{len(targets)} ({progress_percent:.0f}%) completed\n"
                msg += "\n"
            
            msg += f"{get_random_quote()}"
        
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)
    
    elif command == 'status':
        # Simulate the status command
        data = load_data()
        msg = f"{get_random_quote()}\n---\n⏳ **Group Status** ⏳\n\n"
        
        # Next Deadline
        today = datetime.now()
        next_deadline = None
        for ms in data.get("milestones", []):
            deadline_date = datetime.strptime(ms["date"], "%Y-%m-%d")
            if deadline_date > today:
                next_deadline = ms
                break
        
        if next_deadline:
            deadline_date = datetime.strptime(next_deadline["date"], "%Y-%m-%d")
            days_left = (deadline_date - today).days
            msg += f"**NEXT DEADLINE** ({days_left} days left):\n"
            msg += f"🎯 *{next_deadline['description']}* (by {next_deadline['date']})\n\n"
        else:
            msg += "No upcoming deadlines.\n\n"

        # Daily Warriors
        today_str = datetime.now().strftime("%Y-%m-%d")
        msg += "🏃‍♂️ **Warriors in the Arena Today:**\n"
        if today_str in data.get("daily_targets", {}) and data["daily_targets"][today_str]:
            for user_id, user_data in data["daily_targets"][today_str].items():
                msg += f"- {user_data.get('name', 'Unknown')}\n"
        else:
            msg += "- *No one yet. Be the first!* 🔥\n"

        msg += "\nFocus on your daily objective. The obstacle is the way."
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)
    
    else:
        # Custom message
        if message:
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN)

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this command.")
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /schedule HH:MM <command|message> <content>\n\n"
            "Examples:\n"
            "• `/schedule 09:00 view_today` - Show daily targets at 9 AM\n"
            "• `/schedule 18:00 status` - Show group status at 6 PM\n"
            "• `/schedule 07:30 message \"Good morning! Time to conquer the day!\"`"
        )
        return

    chat_id = update.message.chat_id
    try:
        time_str = context.args[0]
        hour, minute = map(int, time_str.split(':'))
        command_type = context.args[1].lower()
        
        if command_type == "message":
            message = " ".join(context.args[2:]).strip('"')
            job_data = {'command': 'custom', 'message': message}
            description = f"custom message"
        elif command_type in ['view_today', 'status']:
            job_data = {'command': command_type}
            description = f"{command_type} command"
        else:
            await update.message.reply_text("Supported commands: view_today, status, message")
            return
        
        # Remove existing scheduled job if any
        job_key = f'scheduled_job_{chat_id}'
        if job_key in context.chat_data:
            context.chat_data[job_key].schedule_removal()

        # Schedule the new job
        job = context.job_queue.run_daily(
            schedule_command_job, 
            time=datetime(1,1,1,hour,minute).time(), 
            chat_id=chat_id,
            data=job_data
        )
        context.chat_data[job_key] = job
        
        await update.message.reply_text(f"✅ Scheduled {description} for {time_str} every day.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /schedule HH:MM <command|message> <content>")

async def stop_scheduled_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can use this command.")
        return
        
    chat_id = update.message.chat_id
    job_key = f'scheduled_job_{chat_id}'
    
    if job_key not in context.chat_data:
        await update.message.reply_text("No scheduled command to stop.")
        return
        
    context.chat_data[job_key].schedule_removal()
    del context.chat_data[job_key]
    await update.message.reply_text("🛑 Scheduled command stopped.")

# --- Member Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I am the GATE Target Tracker. Use /view_plan to see our goals or set your /today target.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🎯 **GATE Target Tracker Commands** 🎯

**📋 General Commands:**
• `/start` - Welcome message and introduction
• `/help` - Show this help message
• `/status` - View group status with stoic quote
• `/view_plan` - Display all milestones and deadlines
• `/view_today` - View all users' daily targets for today

**📚 GATE Syllabus Tracking:**
• `/view_subjects` - See GATE syllabus subjects & topics
• `/view_topics "Subject Name"` - View all topics in a specific subject
• `/complete "Subject" "Topic"` - Mark syllabus topic as completed
• `/dashboard` - View your GATE syllabus progress + daily targets

**🎯 Personal Daily Targets:**
• `/today` - View your targets for today
• `/today <goal>` - Add a personal daily target for today
• `/set_date_target YYYY-MM-DD <goal>` - Set target for specific date
• `/my_targets [date]` - List your targets (today or specific date)
• `/complete_goal <date|today> <number>` - Mark target as completed ✅
• `/edit_target <number> <new_goal>` - Edit one of your daily targets
• `/delete_target <number>` - Delete one of your daily targets

**⚙️ Admin Commands:**
• `/set_milestone YYYY-MM-DD "Description"` - Create new milestone
• `/edit_milestone <number> <date|description> <new_value>` - Edit existing milestone
• `/delete_milestone <number>` - Delete specific milestone
• `/clear_plan` - Remove all milestones
• `/add_subject "Subject Name" topic1,topic2,topic3` - Add GATE syllabus subjects
• `/edit_topics "Subject" <add|remove|replace> <topics>` - Modify topics in subject
• `/delete_topic "Subject" "Topic"` - Delete specific topic from subject
• `/delete_subject "Subject Name"` - Delete subject and all progress data
• `/set_daily_reminder HH:MM` - Set daily reminder (e.g., 07:00)
• `/stop_daily_reminder` - Stop daily reminders
• `/schedule HH:MM <command|message> <content>` - Schedule daily commands
• `/stop_schedule` - Stop scheduled commands

**📖 Examples:**
• `/complete "Mathematics" "Linear Algebra"` - Mark syllabus topic done
• `/view_topics "Mathematics"` - See all topics in Mathematics with your progress
• `/delete_milestone 2` - Delete the 2nd milestone from your plan
• `/delete_topic "Math" "Old Topic"` - Remove specific topic from subject
• `/delete_subject "Old Subject"` - Remove entire subject and all progress
• `/edit_topics "Math" add "Calculus II,Statistics"` - Add new topics to subject
• `/today Complete 2 practice problems` - Add personal daily goal
• `/today` - View your targets for today as checklist
• `/set_date_target 2025-08-10 Review chapter 5` - Set goal for specific date
• `/complete_goal today 1` - Mark your first target as completed ✅
• `/view_today` - See everyone's daily targets with progress
• `/schedule 09:00 view_today` - Auto-show daily targets at 9 AM
• `/add_subject "Computer Science" "Data Structures,Algorithms,DBMS"`

**Key Distinction:**
🔸 **Subjects/Topics** = Official GATE syllabus (same for everyone)
🔸 **Daily Targets** = Your personal daily goals (can be anything)

*"The obstacle is the way." - Marcus Aurelius*
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def set_today_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    
    # If no arguments provided, show today's targets
    if not context.args:
        await show_user_targets_for_date(update, user_id, user_name, datetime.now().strftime("%Y-%m-%d"))
        return
    
    target = " ".join(context.args)
    
    data = load_data()
    today_str = datetime.now().strftime("%Y-%m-%d")
    if today_str not in data["daily_targets"]:
        data["daily_targets"][today_str] = {}
    
    if user_id not in data["daily_targets"][today_str]:
        data["daily_targets"][today_str][user_id] = {"name": user_name, "targets": []}
    
    # Handle data migration from old format to new format
    user_data = data["daily_targets"][today_str][user_id]
    if "targets" not in user_data:
        # Migrate from old format
        if "target" in user_data:
            # Convert old single target or list of strings to new format
            old_targets = user_data["target"]
            if isinstance(old_targets, str):
                # Single target (very old format)
                new_targets = [{"text": old_targets, "completed": False, "completed_at": None}]
            elif isinstance(old_targets, list):
                # List of strings (old format)
                new_targets = []
                for target in old_targets:
                    if isinstance(target, str):
                        new_targets.append({"text": target, "completed": False, "completed_at": None})
                    else:
                        new_targets.append(target)  # Already in new format
            else:
                new_targets = []
            user_data["targets"] = new_targets
            del user_data["target"]  # Remove old key
        else:
            # No targets at all, create empty list
            user_data["targets"] = []
    
    # Add the new target with completion status
    target_obj = {"text": target, "completed": False, "completed_at": None}
    data["daily_targets"][today_str][user_id]["targets"].append(target_obj)
    save_data(data)
    
    target_count = len(data["daily_targets"][today_str][user_id]["targets"])
    await update.message.reply_text(f"✅ Target {target_count} locked in. Make it happen.")

async def view_today_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    if (today_str not in data.get("daily_targets", {}) or 
        not data["daily_targets"][today_str]):
        await update.message.reply_text("No daily targets set for today yet. Be the first with `/today <your goal>`!")
        return
    
    message = "🎯 **Today's Warriors & Their Targets** 🎯\n\n"
    
    for i, (user_id, user_data) in enumerate(data["daily_targets"][today_str].items(), 1):
        user_name = user_data.get("name", "Unknown User")
        targets = user_data.get("targets", user_data.get("target", []))  # Handle both old and new format
        
        # Convert old format to new format if needed
        if targets and isinstance(targets[0], str):
            new_targets = []
            for target in targets:
                new_targets.append({"text": target, "completed": False, "completed_at": None})
            user_data["targets"] = new_targets
            targets = new_targets
            # Remove old format key if it exists
            if "target" in user_data:
                del user_data["target"]
            save_data(data)
        
        message += f"**{i}) {user_name}**\n"
        completed_count = 0
        for j, target_obj in enumerate(targets, 1):
            if isinstance(target_obj, dict):
                if target_obj["completed"]:
                    message += f"   ✅ ~~{target_obj['text']}~~\n"
                    completed_count += 1
                else:
                    message += f"   ⭕ {target_obj['text']}\n"
            else:
                # Handle any remaining old format entries
                message += f"   ⭕ {target_obj}\n"
        
        if targets:
            progress_percent = (completed_count / len(targets)) * 100
            message += f"   📊 {completed_count}/{len(targets)} ({progress_percent:.0f}%) completed\n"
        message += "\n"
    
    message += f"{get_random_quote()}"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def delete_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    
    # Handle cases where update.message might be None
    if not update.message:
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /delete_target <target_number>\n\nExample: `/delete_target 2` to delete your 2nd target for today")
        return
    
    try:
        target_number = int(context.args[0])
        if target_number < 1:
            raise ValueError("Target number must be positive")
    except ValueError:
        await update.message.reply_text("Please provide a valid target number (1, 2, 3, etc.)")
        return
    
    data = load_data()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    if (today_str not in data.get("daily_targets", {}) or 
        user_id not in data["daily_targets"][today_str]):
        await update.message.reply_text("You don't have any daily targets set for today.")
        return
    
    user_targets = data["daily_targets"][today_str][user_id]
    targets = user_targets.get("targets", user_targets.get("target", []))
    
    # Convert old format to new format if needed
    if targets and isinstance(targets[0], str):
        new_targets = []
        for target in targets:
            new_targets.append({"text": target, "completed": False, "completed_at": None})
        user_targets["targets"] = new_targets
        if "target" in user_targets:
            del user_targets["target"]
        targets = new_targets
    
    if target_number > len(targets):
        await update.message.reply_text(f"You only have {len(targets)} target(s) for today. Cannot delete target #{target_number}.")
        return
    
    # Delete the target
    deleted_target = targets.pop(target_number - 1)
    deleted_text = deleted_target["text"] if isinstance(deleted_target, dict) else deleted_target
    
    # If no targets left, remove the user entry for today
    if not targets:
        del data["daily_targets"][today_str][user_id]
        # If no users left for today, remove the date entry
        if not data["daily_targets"][today_str]:
            del data["daily_targets"][today_str]
    
    save_data(data)
    
    remaining_count = len(targets)
    if remaining_count > 0:
        await update.message.reply_text(f"🗑️ Target deleted: _{deleted_text}_\n\nYou have {remaining_count} target(s) remaining for today.")
    else:
        await update.message.reply_text(f"🗑️ Target deleted: _{deleted_text}_\n\nAll your daily targets are now cleared.")

async def edit_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    
    # Handle cases where update.message might be None
    if not update.message:
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /edit_target <target_number> <new_target>\n\nExample: `/edit_target 1 Complete 3 math problems instead of 2`")
        return
    
    try:
        target_number = int(context.args[0])
        if target_number < 1:
            raise ValueError("Target number must be positive")
    except ValueError:
        await update.message.reply_text("Please provide a valid target number (1, 2, 3, etc.)")
        return
    
    new_target = " ".join(context.args[1:])
    
    data = load_data()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    if (today_str not in data.get("daily_targets", {}) or 
        user_id not in data["daily_targets"][today_str]):
        await update.message.reply_text("You don't have any daily targets set for today. Use `/today <goal>` to set one first.")
        return
    
    user_targets = data["daily_targets"][today_str][user_id]
    targets = user_targets.get("targets", user_targets.get("target", []))
    
    # Convert old format to new format if needed
    if targets and isinstance(targets[0], str):
        new_targets = []
        for target in targets:
            new_targets.append({"text": target, "completed": False, "completed_at": None})
        user_targets["targets"] = new_targets
        if "target" in user_targets:
            del user_targets["target"]
        targets = new_targets
    
    if target_number > len(targets):
        await update.message.reply_text(f"You only have {len(targets)} target(s) for today. Cannot edit target #{target_number}.")
        return
    
    # Edit the target
    target_obj = targets[target_number - 1]
    old_target = target_obj["text"] if isinstance(target_obj, dict) else target_obj
    
    if isinstance(target_obj, dict):
        target_obj["text"] = new_target
    else:
        # Convert to new format while editing
        targets[target_number - 1] = {"text": new_target, "completed": False, "completed_at": None}
    
    save_data(data)
    
    await update.message.reply_text(f"✏️ Target #{target_number} updated!\n\n**Old:** _{old_target}_\n**New:** _{new_target}_")

async def list_my_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    
    # Handle cases where update.message might be None
    if not update.message:
        return
    
    # Check if date is specified
    if context.args and len(context.args) > 0:
        date_input = context.args[0]
        if date_input.lower() == "today":
            date_str = datetime.now().strftime("%Y-%m-%d")
        else:
            try:
                # Validate date format
                datetime.strptime(date_input, "%Y-%m-%d")
                date_str = date_input
            except ValueError:
                await update.message.reply_text("Please use the correct date format: YYYY-MM-DD or 'today'\n\nUsage: `/my_targets` for today or `/my_targets YYYY-MM-DD` for specific date")
                return
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    await show_user_targets_for_date(update, user_id, user_name, date_str)

async def complete_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    
    # Handle cases where update.message might be None
    if not update.message:
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /complete \"Subject Name\" \"Topic Name\"\n\nThis marks GATE syllabus topics as completed.")
        return
    
    subject_name = context.args[0].strip('"')
    topic_name = " ".join(context.args[1:]).strip('"')
    
    data = load_data()
    
    # Initialize data structures if needed
    if "subjects" not in data or subject_name not in data["subjects"]:
        await update.message.reply_text(f"GATE syllabus subject '{subject_name}' not found. Use /view_subjects to see available subjects.")
        return
    
    if topic_name not in data["subjects"][subject_name]["topics"]:
        await update.message.reply_text(f"Syllabus topic '{topic_name}' not found in subject '{subject_name}'.")
        return
    
    if "user_progress" not in data:
        data["user_progress"] = {}
    
    if user_id not in data["user_progress"]:
        data["user_progress"][user_id] = {"name": user_name}
    
    if subject_name not in data["user_progress"][user_id]:
        data["user_progress"][user_id][subject_name] = {"completed_topics": []}
    
    # Add topic if not already completed
    if topic_name not in data["user_progress"][user_id][subject_name]["completed_topics"]:
        data["user_progress"][user_id][subject_name]["completed_topics"].append(topic_name)
        data["user_progress"][user_id][subject_name]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        save_data(data)
        
        # Calculate progress
        completed = len(data["user_progress"][user_id][subject_name]["completed_topics"])
        total = data["subjects"][subject_name]["total_topics"]
        percentage = (completed / total) * 100
        
        await update.message.reply_text(f"🎉 GATE syllabus topic completed: '{topic_name}'\n📊 Progress in {subject_name}: {completed}/{total} ({percentage:.1f}%)")
    else:
        await update.message.reply_text(f"Syllabus topic '{topic_name}' already marked as completed!")

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    
    # Handle cases where update.message might be None
    if not update.message:
        return
    
    data = load_data()
    
    if "subjects" not in data or not data["subjects"]:
        await update.message.reply_text("No GATE syllabus subjects available yet. Contact admin to add syllabus.")
        return
    
    message = f"📊 **{user_name}'s GATE Progress Dashboard** 📊\n\n"
    message += "📚 **GATE Syllabus Progress:**\n"
    
    # Get user progress
    user_progress = data.get("user_progress", {}).get(user_id, {})
    
    total_topics_all = 0
    completed_topics_all = 0
    
    for subject_name, subject_info in data["subjects"].items():
        total_topics = subject_info["total_topics"]
        total_topics_all += total_topics
        
        completed_topics = 0
        if subject_name in user_progress and "completed_topics" in user_progress[subject_name]:
            completed_topics = len(user_progress[subject_name]["completed_topics"])
            completed_topics_all += completed_topics
        
        percentage = (completed_topics / total_topics) * 100 if total_topics > 0 else 0
        
        # Progress bar
        filled = int(percentage / 10)
        empty = 10 - filled
        progress_bar = "🟩" * filled + "⬜" * empty
        
        message += f"**{subject_name}**\n"
        message += f"{progress_bar} {percentage:.1f}%\n"
        message += f"📝 {completed_topics}/{total_topics} topics completed\n\n"
    
    # Overall progress
    overall_percentage = (completed_topics_all / total_topics_all) * 100 if total_topics_all > 0 else 0
    overall_filled = int(overall_percentage / 10)
    overall_empty = 10 - overall_filled
    overall_bar = "🟩" * overall_filled + "⬜" * overall_empty
    
    message += f"🎯 **OVERALL GATE SYLLABUS PROGRESS**\n"
    message += f"{overall_bar} {overall_percentage:.1f}%\n"
    message += f"📚 {completed_topics_all}/{total_topics_all} syllabus topics completed\n\n"
    
    # Show today's personal target if set
    today_str = datetime.now().strftime("%Y-%m-%d")
    if (today_str in data.get("daily_targets", {}) and 
        user_id in data["daily_targets"][today_str]):
        user_targets = data["daily_targets"][today_str][user_id]
        targets = user_targets.get("targets", user_targets.get("target", []))
        
        # Handle both old and new format
        if targets and isinstance(targets[0], str):
            new_targets = []
            for target in targets:
                new_targets.append({"text": target, "completed": False, "completed_at": None})
            user_targets["targets"] = new_targets
            targets = new_targets
            if "target" in user_targets:
                del user_targets["target"]
            save_data(data)
        
        message += f"🎯 **Today's Personal Targets:**\n"
        completed_count = 0
        for i, target_obj in enumerate(targets, 1):
            if isinstance(target_obj, dict):
                if target_obj["completed"]:
                    message += f"✅ {i}. ~~{target_obj['text']}~~\n"
                    completed_count += 1
                else:
                    message += f"⭕ {i}. _{target_obj['text']}_\n"
            else:
                # Handle any remaining old format
                message += f"⭕ {i}. _{target_obj}_\n"
        
        if targets:
            progress_percent = (completed_count / len(targets)) * 100
            message += f"📊 Personal targets: {completed_count}/{len(targets)} ({progress_percent:.0f}%) completed\n"
        message += "\n"
    else:
        message += f"💡 **Set your daily target:** `/today <your personal goal>`\n\n"
    
    # Motivational quote
    message += f"{get_random_quote()}"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle cases where update.message might be None
    if not update.message:
        return
        
    data = load_data()
    message = f"{get_random_quote()}\n---\n⏳ **Group Status** ⏳\n\n"
    
    # Next Deadline
    today = datetime.now()
    next_deadline = None
    for ms in data["milestones"]:
        deadline_date = datetime.strptime(ms["date"], "%Y-%m-%d")
        if deadline_date > today:
            next_deadline = ms
            break
    
    if next_deadline:
        deadline_date = datetime.strptime(next_deadline["date"], "%Y-%m-%d")
        days_left = (deadline_date - today).days
        message += f"**NEXT DEADLINE** ({days_left} days left):\n"
        message += f"🎯 *{next_deadline['description']}* (by {next_deadline['date']})\n\n"
    else:
        message += "No upcoming deadlines.\n\n"

    # Daily Warriors
    today_str = datetime.now().strftime("%Y-%m-%d")
    message += "🏃‍♂️ **Warriors in the Arena Today:**\n"
    if today_str in data["daily_targets"] and data["daily_targets"][today_str]:
        for user_id, user_data in data["daily_targets"][today_str].items():
            message += f"- {user_data['name']}\n"
    else:
        message += "- *No one yet. Be the first!* 🔥\n"

    message += "\nFocus on your daily objective. The obstacle is the way."
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


# --- Main Function to Run the Bot ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

async def main():
    application = Application.builder().token(TOKEN).build()

    # Add error handler
    application.add_error_handler(error_handler)

    # Admin commands
    application.add_handler(CommandHandler("set_milestone", set_milestone))
    application.add_handler(CommandHandler("edit_milestone", edit_milestone))
    application.add_handler(CommandHandler("delete_milestone", delete_milestone))
    application.add_handler(CommandHandler("view_plan", view_plan))
    application.add_handler(CommandHandler("clear_plan", clear_plan))
    application.add_handler(CommandHandler("add_subject", add_subject))
    application.add_handler(CommandHandler("edit_topics", edit_topics))
    application.add_handler(CommandHandler("delete_topic", delete_topic))
    application.add_handler(CommandHandler("delete_subject", delete_subject))
    application.add_handler(CommandHandler("set_daily_reminder", set_daily_reminder))
    application.add_handler(CommandHandler("stop_daily_reminder", stop_daily_reminder))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("stop_schedule", stop_scheduled_command))

    # Member commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", set_today_target))
    application.add_handler(CommandHandler("set_date_target", set_date_target))
    application.add_handler(CommandHandler("complete_goal", complete_goal))
    application.add_handler(CommandHandler("view_today", view_today_targets))
    application.add_handler(CommandHandler("my_targets", list_my_targets))
    application.add_handler(CommandHandler("edit_target", edit_target))
    application.add_handler(CommandHandler("delete_target", delete_target))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("view_subjects", view_subjects))
    application.add_handler(CommandHandler("view_topics", view_topics))
    application.add_handler(CommandHandler("complete", complete_topic))
    application.add_handler(CommandHandler("dashboard", dashboard))

    logger.info("Bot is starting...")
    await application.run_polling()


if __name__ == '__main__':
    import asyncio
    import nest_asyncio
    
    # Apply nest_asyncio to allow nested event loops
    nest_asyncio.apply()
    
    # More robust event loop handling
    try:
        # Try to get current event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running, just run the coroutine
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, main())
                future.result()
        else:
            # Loop exists but not running, run normally
            loop.run_until_complete(main())
    except RuntimeError:
        # No event loop exists, create one and run
        asyncio.run(main())