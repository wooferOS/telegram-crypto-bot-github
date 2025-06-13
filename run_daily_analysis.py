import asyncio

from daily_analysis import daily_analysis_task


if __name__ == "__main__":
    asyncio.run(daily_analysis_task())
