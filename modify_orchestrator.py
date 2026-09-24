import sys
path = r'C:\Users\Prakhar Singh\Desktop\UAT_Servicenow\UAT_poc\src\agent\cognition\orchestrator.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. run_cognitive_loop start check
target1 = '''            logger.info(
                "executing_hypothesis", hyp_id=hypothesis.id, capability=hypothesis.capability
            )'''

replace1 = target1 + '''

            # Stuck detection: check before executing next step
            stuck_result = self._stuck_detector.check()
            if stuck_result.is_stuck:
                logger.warning(
                    "agent_stuck_detected",
                    reason=stuck_result.reason,
                    repeated_action=stuck_result.repeated_action,
                    repetition_count=stuck_result.repetition_count,
                )
                memory.add_timeline_entry(
                    action="Stuck detection triggered",
                    result=stuck_result.reason,
                )
                self._transition(
                    AgentState.FAILED,
                    f"Agent stuck in action loop: {stuck_result.reason}",
                )
                return'''

# 2. run_cognitive_loop record action
target2 = '''            if self._perception_engine:
                result = await self._perception_engine.execute_with_perception(action)
            else:
                result = await self._execution_controller.execute(action)  # type: ignore[union-attr]'''

replace2 = target2 + '''

            # Record action for stuck detection
            self._stuck_detector.record(
                str(action.action_type),
                str(action.target),
                url=raw_obs.url if raw_obs and hasattr(raw_obs, "url") else "",
            )'''

content = content.replace(target1, replace1)

# 3. _execute_canonical_plan check
target3 = '''            step.mark_in_progress()
            logger.info("executing_plan_step", step_index=step.step_index, description=step.description)'''

replace3 = '''            # Stuck detection: check before executing next step
            stuck_result = self._stuck_detector.check()
            if stuck_result.is_stuck:
                logger.warning(
                    "agent_stuck_detected",
                    reason=stuck_result.reason,
                    repeated_action=stuck_result.repeated_action,
                    repetition_count=stuck_result.repetition_count,
                )
                step.mark_failed(f"Agent stuck: {stuck_result.reason}")
                memory.add_timeline_entry(
                    action="Stuck detection triggered",
                    result=stuck_result.reason,
                )
                await self._publish_event(
                    RunEventType.STEP_FINISHED,
                    {
                        "step_index": step.step_index,
                        "description": step.description,
                        "status": "failed",
                        "actual_result": f"Agent stuck: {stuck_result.reason}",
                    },
                )
                # Abort remaining steps — don't waste more time
                plan.skip_remaining_steps(
                    step.step_index + 1,
                    f"Skipped: agent detected stuck in loop ({stuck_result.repeated_action})",
                )
                self._transition(
                    AgentState.FAILED,
                    f"Agent stuck in action loop: {stuck_result.reason}",
                )
                return

            step.mark_in_progress()
            logger.info("executing_plan_step", step_index=step.step_index, description=step.description)'''

content = content.replace(target3, replace3)

# 4. Replace both target2 instances with replace2
content = content.replace(target2, replace2)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Done modifying orchestrator')
