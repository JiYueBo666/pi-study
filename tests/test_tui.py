"""TUI 状态行为测试。"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.widgets import Collapsible, Static

from agent_core.events import AgentEnded, SteeringQueued
from ai.types import ToolCallContent, UserMessage
from coding_agent.commands import CommandContext, CommandRegistry, register_builtin_commands
from coding_agent.event import ToolApprovalRequest
from tui.widgets import MessageList, ToolResultView, _output_lexer
from tui_app.app import MyPiApp
from tui_app.screens import SessionPickerScreen


class _HostApp(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


class _ToolResultHost(App):
    def __init__(self, view: ToolResultView) -> None:
        super().__init__()
        self.view = view

    def compose(self) -> ComposeResult:
        yield self.view


def _session() -> dict:
    return {
        "id": "sess_abc",
        "cwd": "/tmp/workspace",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "message_count": 1,
    }


def test_session_picker_keeps_row_when_delete_fails() -> None:
    sessions = [_session()]
    screen = SessionPickerScreen(sessions, on_load=lambda _: None, on_delete=lambda _: False)

    async def run() -> None:
        app = _HostApp()
        async with app.run_test(size=(80, 20)) as pilot:
            app.push_screen(screen)
            await pilot.pause()
            screen.on_key(SimpleNamespace(key="d"))
            assert len(sessions) == 1

    import asyncio

    asyncio.run(run())


def test_bash_result_has_separate_command_exit_code_and_output() -> None:
    view = ToolResultView(
        tool_name="bash",
        content="2 passed\n",
        details={"command": "pytest -q", "exit_code": 0},
        is_error=False,
    )

    async def run() -> None:
        app = _ToolResultHost(view)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            command = app.query_one(".tool-result-command", Static)
            exit_code = app.query_one(".tool-result-exit", Static)
            output = app.query_one(".tool-result-output", Static)

            assert isinstance(command.content, Syntax)
            assert "pytest -q" in command.content.code
            assert "0" in str(exit_code.content)
            assert isinstance(output.content, Syntax)
            assert "2 passed" in output.content.code

    import asyncio

    asyncio.run(run())


def test_long_tool_output_is_collapsed_and_can_expand() -> None:
    view = ToolResultView(
        tool_name="bash",
        content="\n".join(f"line {number}" for number in range(20)),
        details={"command": "pytest -vv", "exit_code": 1},
        is_error=True,
    )

    async def run() -> None:
        app = _ToolResultHost(view)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            collapsible = app.query_one(Collapsible)
            assert view.output_is_long
            assert collapsible.collapsed

            collapsible.collapsed = False
            await pilot.pause()
            assert not collapsible.collapsed

    import asyncio

    asyncio.run(run())


def test_read_result_uses_file_extension_for_syntax() -> None:
    assert _output_lexer("read", {"path": "src/app.py"}) == "python"
    assert _output_lexer("read", {"path": "README.unknown"}) == "text"


def test_approval_prompt_renders_untrusted_command_as_plain_text() -> None:
    """审批命令包含 markup 字符时，TUI 仍应正常渲染。"""
    request = ToolApprovalRequest(
        request_id="approval-1",
        tool_name="bash",
        tool_description="执行 shell 命令",
        call=ToolCallContent(
            id="call-1",
            name="bash",
            arguments={"command": "python -c 'print(\"[x]\\n\")'"},
        ),
    )

    class FakeController:
        workspace = Path("/tmp/project")
        session = SimpleNamespace(session_id=None, model=SimpleNamespace(id="test-model"))
        registry = SimpleNamespace(command_names=lambda: ())

        def subscribe(self, handler) -> None:
            pass

        def resolve_approval(self, request_id: str, approved: bool) -> bool:
            return True

    async def run() -> None:
        app = MyPiApp(controller=FakeController())  # type: ignore[arg-type]
        async with app.run_test(size=(80, 24)) as pilot:
            app._show_approval_prompt(request)
            await pilot.pause()
            approval = next(
                child
                for child in app.query_one(MessageList).children
                if child.has_class("approval")
            )
            assert isinstance(approval, Static)
            content = str(approval.content)
            assert "工具调用需要审批" in content
            assert str(request.call.arguments) in content
            assert "允许执行？输入 y / n" in content
            '''
                "⚠️  工具调用需要审批\n\n"
                "工具：bash\n"
                "说明：执行 shell 命令\n"
                "参数：{'command': 'python -c \'print(\"[x]\\n\")\'}\n\n"
                "允许执行？输入 y / n"
            '''

    asyncio.run(run())


def test_clear_command_only_clears_tui_messages() -> None:
    registry = CommandRegistry()
    register_builtin_commands(registry)
    history = (SimpleNamespace(role="user", content="保留的历史"),)
    session = SimpleNamespace(
        session_id=None,
        model=SimpleNamespace(id="test-model"),
        messages=history,
    )

    class FakeController:
        workspace = Path("/tmp/project")

        def __init__(self) -> None:
            self.registry = registry
            self.session = session

        def subscribe(self, handler) -> None:
            pass

        async def run_command(self, text: str):
            return await registry.execute(text, CommandContext(session=session))

    async def run() -> None:
        app = MyPiApp(controller=FakeController())  # type: ignore[arg-type]
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.query_one(MessageList).children

            await pilot.click("#input")
            await pilot.press(*"/clear")
            await pilot.press("enter")
            await pilot.pause()

            assert not app.query_one(MessageList).children
            assert session.messages == history

    asyncio.run(run())


def test_running_input_is_queued_and_steering_event_is_highlighted() -> None:
    registry = CommandRegistry()
    register_builtin_commands(registry)
    session = SimpleNamespace(
        session_id=None,
        model=SimpleNamespace(id="test-model"),
        messages=(),
    )

    class FakeController:
        workspace = Path("/tmp/project")

        def __init__(self) -> None:
            self.registry = registry
            self.session = session
            self.handler = None
            self.prompt_started = asyncio.Event()
            self.release_prompt = asyncio.Event()
            self.steering: list[str] = []

        def subscribe(self, handler) -> None:
            self.handler = handler

        async def run_prompt(self, text: str) -> str:
            self.prompt_started.set()
            await self.release_prompt.wait()
            return "done"

        def steer(self, text: str) -> bool:
            self.steering.append(text)
            return True

    async def run() -> None:
        controller = FakeController()
        app = MyPiApp(controller=controller)  # type: ignore[arg-type]
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.click("#input")
            await pilot.press(*"first task")
            await pilot.press("enter")
            await controller.prompt_started.wait()

            await pilot.press(*"check session.py first")
            await pilot.press("enter")
            await pilot.pause()
            assert controller.steering == ["check session.py first"]

            assert controller.handler is not None
            controller.handler(
                SteeringQueued(
                    turn=2,
                    messages=(
                        UserMessage(
                            content="check session.py first",
                            timestamp=datetime.now(UTC),
                        ),
                    ),
                )
            )
            await pilot.pause()

            steering_views = [child for child in app.query_one(MessageList).children if child.has_class("steering")]
            assert len(steering_views) == 1
            steering_view = steering_views[0]
            assert isinstance(steering_view, Static)
            assert "下一轮 3" in str(steering_view.content)
            assert "check session.py first" in str(steering_view.content)

            controller.release_prompt.set()
            await pilot.pause()

    asyncio.run(run())


def test_model_failure_displays_provider_error_detail() -> None:
    registry = CommandRegistry()
    register_builtin_commands(registry)
    session = SimpleNamespace(
        session_id=None,
        model=SimpleNamespace(id="test-model"),
        messages=(),
    )

    class FakeController:
        workspace = Path("/tmp/project")

        def __init__(self) -> None:
            self.registry = registry
            self.session = session

        def subscribe(self, handler) -> None:
            self.handler = handler

    async def run() -> None:
        controller = FakeController()
        app = MyPiApp(controller=controller)  # type: ignore[arg-type]
        async with app.run_test(size=(80, 24)) as pilot:
            controller.handler(
                AgentEnded(
                    status="model_failed",
                    error="AuthenticationError: invalid API key",
                )
            )
            await pilot.pause()

            error_views = [child for child in app.query_one(MessageList).children if child.has_class("error")]
            assert len(error_views) == 1
            error_view = error_views[0]
            assert isinstance(error_view, Static)
            assert "模型调用失败" in str(error_view.content)
            assert "AuthenticationError: invalid API key" in str(error_view.content)

    asyncio.run(run())
