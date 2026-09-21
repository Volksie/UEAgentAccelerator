---
system: Character startup
modules: [AccelDemo, AccelDemoCore]
classes: [AADCharacter, UADStaminaComponent]
status: current
source: reconstructed 2026-09-12 from the code and its comments
---

# Character startup

## What exists before BeginPlay

*AADCharacter*'s constructor does three things: it turns the character's own tick off, marks the actor as replicated, and creates its stamina component as a default subobject named `Stamina`.

The character does not tick because it has nothing to do per frame. The per-frame work is stamina regeneration, and that belongs to the component, which ticks and replicates by default.

## The one-frame deferral in BeginPlay

The first stamina top-up does not happen in *BeginPlay*. It is scheduled for the next tick.

This is a workaround, and it is marked as one in the code with a `HACK:` comment. On clients, the stamina component has not finished receiving its replicated default values when *BeginPlay* runs. A top-up at that point writes into a pool that initial replication is about to overwrite, so the write is lost. Deferring by one frame puts it after the replicated values have landed.

**It is meant to be removed.** The condition is the engine issue the comment names, UE-1234567: once initial replication is ordered before *BeginPlay* on the owning client, the deferral has no job and the top-up can move back into *BeginPlay*.

When changing this, read the body under the comment rather than trusting either this document or the comment about what the deferred call currently does.

## Who runs what

Regeneration is server authoritative: the component's tick returns early unless its owner has authority. Clients see the result through the replicated stamina value. Running regen on a client would only fight the next update from the server.
