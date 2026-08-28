# Using Scheduler

Runs a script again every so often, without a sleep loop written into the
script — which matters, because a script with its own loop can only ever be
run that way.

## From the console

```
every 300 backup.py        # run it every five minutes
jobs                       # what is scheduled, and when each runs next
jobs stop job1
jobs stop all
```

The first run happens immediately, then it waits the interval between runs.
The shortest interval is five seconds.

## From the panel

**Servers → Scheduled jobs**. Type a script and an interval, press **Schedule
it**. Each job shows how many times it has run, how many of those failed, and
how long until the next one. **Run now** runs it once without disturbing the
schedule.

## What a job is

Each job is a thread that sleeps between runs, so a job that is waiting costs
nothing. A run happens in a fresh namespace — the same isolation a script
server gets — so a job cannot disturb what you are doing in the console.

If a run raises, the failure is counted, the error is shown on the job, the
traceback goes to the debug console, and the schedule carries on. A job that
fails every time is a job you can see failing rather than one that quietly
stopped.

## The honest limit

Jobs live for as long as PyCmd is open. Android gives an app no promise of
being alive later — it can be stopped at any time to free memory — so nothing
here claims a schedule that survives being closed. If you need something to run
while the app is not, this is the wrong tool and no plugin can be the right
one.
