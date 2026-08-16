from __future__ import annotations

import asyncio
from collections.abc import Callable


class EventStream[T, R]:
    def __init__(self, is_complete: Callable[[T], bool], extract_result: Callable[[T], R]):

        # 待消费事件队列
        self._queue: list[T] = []
        # 等待数据的消费者Future列表：每个 Future 在 push 时 resolve 出事件，
        # 在 end 时以 StopAsyncIteration 异常结束（等价 TS 的 IteratorResult{done}）
        self._waiting: list[asyncio.Future[T]] = []

        # 流是否已经结束
        self._done: bool = False

        # 最终结果Promise/Future
        self._final_result_fut: asyncio.Future[R] = asyncio.Future()

        # 回调函数
        self._is_complete = is_complete
        self._extract_result = extract_result

    def push(self, event: T):
        if self._done:
            return

        # 判断事件是否结束
        if self._is_complete(event):
            self._done = True
            res = self._extract_result(event)
            self._final_result_fut.set_result(res)
        # 唤醒一个消费者，否则存入队列
        if self._waiting:
            waiter = self._waiting.pop(0)
            waiter.set_result(event)
        else:
            self._queue.append(event)

    def end(self, result: R | None = None) -> None:
        """手动强制关闭流"""
        if self._done:
            return
        self._done = True

        if result is not None:
            self._final_result_fut.set_result(result)

        # 唤醒所有等待的消费者，标记迭代结束
        while self._waiting:
            waiter = self._waiting.pop(0)
            waiter.set_exception(StopAsyncIteration)

    def __aiter__(self) -> EventStream[T, R]:
        # 异步迭代入口：返回 self，__anext__ 负责逐项产出
        return self

    async def __anext__(self) -> T:
        """异步迭代下一项（对应TS async iterator）"""
        while True:
            # 队列有数据，直接取出返回
            if self._queue:
                return self._queue.pop(0)
            # 流已结束，终止迭代
            if self._done:
                raise StopAsyncIteration
            # 无数据：创建Future挂起等待生产者push
            fut: asyncio.Future[T] = asyncio.Future()
            self._waiting.append(fut)
            try:
                return await fut
            except StopAsyncIteration:
                raise

    async def result(self) -> R:
        """等待流式全部结束，获取最终完整结果"""
        return await self._final_result_fut
