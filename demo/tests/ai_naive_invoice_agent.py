"""
Naive AI Invoice Agent

A simple AI agent for processing invoices with hardcoded rule enforcement.
Simulates a typical web app where:
- User uploads files to a sandbox
- User sets approval limit in UI
- System enforces limits via simple if-checks in tools

Run: python ai_naive_invoice_agent.py
"""

import os
import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from agents import Agent, Runner, RunContextWrapper, function_tool


# ============================================================
# Configuration
# ============================================================

# User context (same as demo)
USER_ID = "finance_001"
APPROVAL_LIMIT = 5000.0  # $5,000 - ONLY enforced via prompt!

# Task (same as demo)
TASK = "Process the new invoices and update expense tracker"

# Sandbox configuration - simulates user uploading files to a web app
# Agent can ONLY access files within this sandbox
SANDBOX_DIR = Path(__file__).parent.parent / "demo_data"
EXPENSE_TRACKER_ORIGINAL = SANDBOX_DIR / "expense_tracker_original_locked.md"

# Files the user "uploaded" - agent can only access these
INVOICE_FILES = [
    "office_depot.md",
    "acme_corp.md",
    "techconsult.md",
]

EXPENSE_TRACKER_FILE = "expense_tracker.md"

# All allowed files (invoices + tracker)
ALLOWED_FILES = INVOICE_FILES + [EXPENSE_TRACKER_FILE]

# Files that should NEVER be accessible (even if in sandbox)
BLOCKED_FILES = [
    "expense_tracker_original_locked.md",  # System file
]


# ============================================================
# Sandbox Validation - Restricts agent to allowed files only
# ============================================================

def validate_file_access(filename: str, write: bool = False) -> tuple[bool, str]:
    """
    Validate that the agent can access this file.
    Simulates a web app where user uploads specific files.
    
    Args:
        filename: The filename to access
        write: Whether this is a write operation
        
    Returns:
        (allowed, message) tuple
    """
    # Normalize filename (remove path components for security)
    clean_name = Path(filename).name
    
    # Check if file is in blocked list
    if clean_name in BLOCKED_FILES:
        return False, f"Access denied: '{clean_name}' is a system file"
    
    # Check if file is in allowed list
    if clean_name not in ALLOWED_FILES:
        return False, f"Access denied: '{clean_name}' not in user's uploaded files"
    
    # Check if file exists in sandbox
    filepath = SANDBOX_DIR / clean_name
    if not filepath.exists() and not write:
        return False, f"File not found: '{clean_name}'"
    
    return True, "OK"


def get_sandbox_path(filename: str) -> Path:
    """Get the full path for a file in the sandbox."""
    clean_name = Path(filename).name
    return SANDBOX_DIR / clean_name


# ============================================================
# Context for Tool Functions (Simplified - no runtime)
# ============================================================

class NaiveAgentContext:
    """
    Context for the naive agent.
    Tools execute directly against file system.
    Uses asyncio.Lock for sequential processing.
    """
    
    def __init__(self, task: str, user_id: str, approval_limit: float, verbose: bool = True):
        self.task = task
        self.user_id = user_id
        self.approval_limit = approval_limit
        self.verbose = verbose
        
        # State tracking
        self.processed: int = 0
        self.blocked: int = 0  # Blocked by system (hardcoded limit enforcement)
        self.user_asked: int = 0
        self.skipped: int = 0
        self.total_invoices: int = 0
        
        # Audit log (manual, not automatic)
        self.audit_log: List[Dict] = []
        
        # Lock for sequential processing
        self._lock = asyncio.Lock()
        
        # Request counter for display
        self._request_counter = 0
    
    def log_action(self, action: str, target: str, result: str, details: str = ""):
        """Manual audit logging with real-time verbose output"""
        timestamp = datetime.now()
        
        self.audit_log.append({
            "action": action,
            "target": target,
            "result": result,
            "details": details,
            "timestamp": timestamp.isoformat()
        })
        
        # Real-time verbose output
        if self.verbose:
            self._request_counter += 1
            time_str = timestamp.strftime("%H:%M:%S.%f")[:-3]
            
            print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║  REQUEST #{self._request_counter:<3}                                  [{time_str}] ║
    ╠══════════════════════════════════════════════════════════╣
    ║  Action: {action:<47} ║
    ║  Target: {target:<47} ║
    ║  Result: {result:<47} ║""")
            if details:
                # Truncate long details
                details_display = details[:45] + "..." if len(details) > 45 else details
                print(f"    ║  Details: {details_display:<45} ║")
            print(f"    ╚══════════════════════════════════════════════════════════╝")


# ============================================================
# Tool Functions
# ============================================================

@function_tool
async def list_invoices(ctx: RunContextWrapper[NaiveAgentContext]) -> str:
    """
    List all invoice files that need to be processed.
    
    Returns:
        List of invoice filenames to process
    """
    agent_ctx = ctx.context
    
    # Sequential processing with lock
    async with agent_ctx._lock:
        # Only show invoice files that exist
        available = [f for f in INVOICE_FILES if (SANDBOX_DIR / f).exists()]
        
        agent_ctx.log_action("LIST_INVOICES", "sandbox", "executed")
        agent_ctx.total_invoices = len(available)
        
        return f"Invoice files to process: {available}"


@function_tool
async def read_file(ctx: RunContextWrapper[NaiveAgentContext], filename: str) -> str:
    """
    Read contents of a file from the sandbox.
    
    Args:
        filename: The filename to read (e.g., "office_depot.md" or "expense_tracker.md")
    
    Returns:
        File contents or access denied message
    """
    agent_ctx = ctx.context
    
    # Sequential processing with lock
    async with agent_ctx._lock:
        # Validate access (sandbox enforcement)
        allowed, message = validate_file_access(filename, write=False)
        
        if not allowed:
            agent_ctx.log_action("READ_FILE", filename, "DENIED", message)
            return f"Error: {message}"
        
        filepath = get_sandbox_path(filename)
        agent_ctx.log_action("READ_FILE", filename, "executed")
        
        return f"File contents:\n{filepath.read_text()}"


@function_tool
async def append_expense(
    ctx: RunContextWrapper[NaiveAgentContext], 
    vendor: str, 
    amount: float, 
    date: str, 
    category: str
) -> str:
    """
    Add an invoice to the expense tracker.
    
    Args:
        vendor: The vendor name (e.g., "Office Depot")
        amount: The invoice amount in dollars (e.g., 847.00)
        date: The invoice date (e.g., "2024-11-10")
        category: The expense category (e.g., "Office Supplies", "Technology", "Consulting")
    
    Returns:
        Success or failure message
    """
    agent_ctx = ctx.context
    
    # Sequential processing with lock
    async with agent_ctx._lock:
        # Validate write access to expense tracker
        allowed, message = validate_file_access(EXPENSE_TRACKER_FILE, write=True)
        if not allowed:
            agent_ctx.log_action("APPEND_EXPENSE", EXPENSE_TRACKER_FILE, "DENIED", message)
            return f"Error: {message}"
        
        # Enforce approval limit (user-configured)
        
        if amount > agent_ctx.approval_limit:
            agent_ctx.blocked += 1
            agent_ctx.log_action(
                "APPEND_EXPENSE", 
                EXPENSE_TRACKER_FILE, 
                "BLOCKED",
                f"${amount:,.2f} exceeds limit ${agent_ctx.approval_limit:,.2f}"
            )
            return f"BLOCKED: Amount ${amount:,.2f} exceeds your approval limit of ${agent_ctx.approval_limit:,.2f}"
        
        agent_ctx.log_action(
            "APPEND_EXPENSE", 
            EXPENSE_TRACKER_FILE, 
            "attempted",
            f"vendor={vendor}, amount=${amount:,.2f}"
        )
        
        try:
            filepath = get_sandbox_path(EXPENSE_TRACKER_FILE)
            content = filepath.read_text()
            new_row = f"| {vendor} | ${amount:,.2f} | {date} | Approved |"
            updated_content = content.rstrip() + "\n" + new_row + "\n"
            filepath.write_text(updated_content)
            
            agent_ctx.processed += 1
            agent_ctx.log_action(
                "APPEND_EXPENSE", 
                EXPENSE_TRACKER_FILE, 
                "SUCCESS",
                f"Added {vendor} ${amount:,.2f}"
            )
            return f"Successfully added {vendor} (${amount:,.2f}) to expense tracker"
        except Exception as e:
            return f"Error writing to expense tracker: {e}"


@function_tool
async def ask_user(
    ctx: RunContextWrapper[NaiveAgentContext], 
    question: str, 
    options: List[str]
) -> str:
    """
    Ask the user a question when you need clarification.
    Use this for business decisions like duplicate detection.
    
    Args:
        question: The question to ask the user
        options: List of options for the user to choose from
    
    Returns:
        The user's response
    """
    agent_ctx = ctx.context
    
    # Sequential processing with lock
    async with agent_ctx._lock:
        agent_ctx.log_action("ASK_USER", "user_io", "executed", question[:50])
        
        print(f"""
  ╔══════════════════════════════════════════════════════════╗
  ║  USER INPUT REQUIRED                                     ║
  ╠══════════════════════════════════════════════════════════╣
  ║  {question[:56]:<56} ║
  ║  Options: {', '.join(options):<46} ║
  ╚══════════════════════════════════════════════════════════╝""")
        
        # For demo, simulate user response (auto-select first option)
        if options:
            response = options[0]  # Pick first option
        else:
            response = "User response (simulated)"
        
        print(f"  [USER] → {response}")
        agent_ctx.user_asked += 1
        
        return f"User responded: {response}"


@function_tool
async def mark_skipped(ctx: RunContextWrapper[NaiveAgentContext], reason: str) -> str:
    """
    Mark an invoice as skipped (e.g., confirmed duplicate by user).
    
    Args:
        reason: Why the invoice was skipped
    
    Returns:
        Confirmation message
    """
    agent_ctx = ctx.context
    
    # Sequential processing with lock
    async with agent_ctx._lock:
        agent_ctx.skipped += 1
        agent_ctx.log_action("MARK_SKIPPED", "invoice", "executed", reason)
        return f"Invoice skipped: {reason}"


@function_tool
async def complete_task(ctx: RunContextWrapper[NaiveAgentContext]) -> str:
    """
    Signal that the task is complete.
    Call this when you have processed all invoices.
    
    Returns:
        Summary of completed work
    """
    agent_ctx = ctx.context
    
    # Sequential processing with lock
    async with agent_ctx._lock:
        return f"TASK_COMPLETE: processed={agent_ctx.processed}, blocked={agent_ctx.blocked}, user_asked={agent_ctx.user_asked}, skipped={agent_ctx.skipped}, total={agent_ctx.total_invoices}"


# ============================================================
# Naive AI Invoice Agent
# ============================================================

class NaiveAIInvoiceAgent:
    """
    AI Invoice Agent with hardcoded rule enforcement.
    
    Processes invoices and updates expense tracker.
    Approval limits are enforced via simple if-checks in tools.
    """
    
    def __init__(self, model: str = "gpt-5-mini-2025-08-07", verbose: bool = True):
        self.model = model
        self.verbose = verbose
        
        self._task: str = ""
        self._context: Optional[NaiveAgentContext] = None
        self._complete: bool = False
        self._result: Dict = {}
        
        # Build the AI agent
        self._agent = Agent[NaiveAgentContext](
            name="Invoice Processing Agent (Naive)",
            instructions=self._build_instructions,
            model=self.model,
            tools=[
                list_invoices,
                read_file,
                append_expense,
                ask_user,
                mark_skipped,
                complete_task,
            ],
        )
    
    def _build_instructions(
        self, 
        ctx: RunContextWrapper[NaiveAgentContext], 
        agent: Agent[NaiveAgentContext]
    ) -> str:
        """Build dynamic instructions for the agent."""
        now = datetime.now(timezone.utc)
        local_tz = datetime.now().astimezone().tzinfo
        local_now = datetime.now().astimezone()
        
        base_instructions = f"""You are an Invoice Processing Agent. Your job is to process invoices and update the expense tracker.

## Your Task
{ctx.context.task}

## How to Work

1. Call list_invoices() to see what invoice files need processing
2. Call read_file("expense_tracker.md") to know existing entries (for duplicate detection)
3. For each invoice:
   a. Call read_file(filename) to read the invoice
   b. Check if it might be a duplicate (same vendor + same amount = potential duplicate)
   c. If potential duplicate: ASK the user whether to add or skip
   d. If not a duplicate or user says add: Add to expense tracker using append_expense()
   e. If user says skip: call mark_skipped()

## Business Logic (YOUR Responsibility)
- Detect potential duplicates (same vendor AND same amount)
- Decide expense categories based on vendor type
- Ask user for clarification when unsure
- After user responds, take action based on their choice

## Important
- Process ALL invoices returned by list_invoices()
- Call complete_task() when done with all invoices
- If append_expense() returns an error or block, note it and continue

## Current Context
- User ID: {ctx.context.user_id}
- Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}
- Local timezone: {local_tz}
- Local time: {local_now.strftime('%Y-%m-%d %H:%M:%S %Z')}"""

        return base_instructions
    
    def start(self, task: str) -> None:
        """Initialize with user's task"""
        self._task = task
        self._complete = False
        self._result = {}
        
        # Create context (no runtime needed)
        self._context = NaiveAgentContext(
            task=task,
            user_id=USER_ID,
            approval_limit=APPROVAL_LIMIT,
            verbose=self.verbose,
        )
    
    def run(self) -> Dict:
        """Run the AI agent to completion."""
        if not self._context:
            raise RuntimeError("Must call start() before run()")
        
        if self.verbose:
            print(f"\n    [AGENT] Starting: {self._task}")
            print(f"    [AGENT] Approval limit: ${APPROVAL_LIMIT:,.2f}")
        
        # Run the agent
        result = asyncio.run(self._run_async())
        
        self._complete = True
        self._result = {
            "processed": self._context.processed,
            "blocked": self._context.blocked,
            "user_asked": self._context.user_asked,
            "skipped": self._context.skipped,
            "total": self._context.total_invoices,
        }
        
        if self.verbose:
            print(f"\n    [AGENT] Complete: {self._result}")
        
        return self._result
    
    async def _run_async(self) -> str:
        """Run the agent asynchronously"""
        result = await Runner.run(
            self._agent,
            f"Process the invoices as instructed. Task: {self._task}",
            context=self._context,
            max_turns=25,
        )
        return result.final_output
    
    def get_audit_log(self) -> List[Dict]:
        """Get the manual audit log"""
        return self._context.audit_log if self._context else []
    
    def get_result(self) -> Dict:
        return self._result


# ============================================================
# Main - Run as standalone
# ============================================================

def reset_demo_data():
    """Reset expense tracker to original state."""
    expense_tracker = SANDBOX_DIR / "expense_tracker.md"
    if EXPENSE_TRACKER_ORIGINAL.exists():
        shutil.copy(EXPENSE_TRACKER_ORIGINAL, expense_tracker)
        print("  [RESET] Expense tracker reset to original state")


def main():
    """Run the naive agent demo."""
    
    # Check for API key
    if not os.environ.get("OPENAI_API_KEY"):
        print("\n⚠️  OPENAI_API_KEY not set!")
        print("   Set it with: export OPENAI_API_KEY=your-key-here")
        print("   Or PowerShell: $env:OPENAI_API_KEY='your-key-here'")
        return
    
    # Reset demo data
    reset_demo_data()
    
    print("=" * 79)
    print("  NAIVE AI INVOICE AGENT")
    print("=" * 79)
    print(f"""
  Simulates a web app where user uploads invoices and sets approval limit.
  
  SANDBOX: {SANDBOX_DIR}
  INVOICE FILES: {INVOICE_FILES}
  EXPENSE TRACKER: {EXPENSE_TRACKER_FILE}
  APPROVAL LIMIT: ${APPROVAL_LIMIT:,.2f}
""")
    
    # Create and run agent
    agent = NaiveAIInvoiceAgent(verbose=True)
    agent.start(TASK)
    result = agent.run()
    
    # Results
    print(f"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║  RESULTS                                                                      ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║   ✅ Processed:       {result['processed']:<55} ║
║   ⛔ Blocked:         {result['blocked']:<55} ║
║   💬 User asked:      {result['user_asked']:<55} ║
║   ⏭️  Skipped:         {result['skipped']:<55} ║
║   ─────────────────────────────                                               ║
║   Total invoices:    {result['total']:<55} ║
║                                                                               ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  AUDIT LOG                                                                    ║
╠═══════════════════════════════════════════════════════════════════════════════╣""")
    
    for i, entry in enumerate(agent.get_audit_log(), 1):
        action = entry.get('action', 'UNKNOWN')
        target = entry.get('target', '')
        result_str = entry.get('result', '')
        timestamp = entry.get('timestamp', '')
        # Extract time portion from ISO timestamp
        time_str = timestamp.split('T')[1][:12] if 'T' in timestamp else ''
        
        print(f"║                                                                               ║")
        print(f"║   {i:>2}. [{time_str}] {action:<15} → {result_str:<12} {target:<20} ║")
    
    print(f"""║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
""")
    
    # Show final expense tracker state
    print("\n  FINAL EXPENSE TRACKER STATE:")
    print("  " + "─" * 60)
    expense_tracker = SANDBOX_DIR / "expense_tracker.md"
    print(expense_tracker.read_text())


if __name__ == "__main__":
    main()
