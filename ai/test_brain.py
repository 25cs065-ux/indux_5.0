from brain import safety_check, check_step_reply, ask

def run_quick_checks():
    print("--- 1. Testing Safety Trigger ---")
    safety_res = safety_check("Warning: high voltage capacitor and electrical wiring issue")
    print(f"Safety checklist items returned: {len(safety_res)}")
    for item in safety_res:
        print(f" - {item}")

    print("\n--- 2. Testing Voice Intent Classifier ---")
    reply = check_step_reply("Yeah looks good, pressure is sitting at 90 psi", "Is the pressure above 80 PSI?")
    print(f"Classified Intent: {reply}")

    print("\n--- 3. Testing Out-of-Scope (NOT_FOUND) Handling ---")
    result = ask("How do I bake chocolate chip cookies?")
    print("Status:", result.get("status"))
    print("Escalate to engineer:", result.get("escalate_to_engineer"))
    print("Steps list is empty:", result.get("steps") == [])
    print("Summary:", result.get("summary"))

if __name__ == "__main__":
    run_quick_checks()