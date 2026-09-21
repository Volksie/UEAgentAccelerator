---
system: Combat and health
modules: [AccelDemo, AccelDemoCore]
classes: [AADCharacter, UADStaminaComponent]
status: current
source: reconstructed 2026-09-12 from the code and its comments
---

# Combat and health

A character's health is a float clamped between 0 and *MaxHealth*. The server owns it. Clients only ever receive it.

## One way in: ApplyDamage

Every change to health goes through *AADCharacter::ApplyDamage*. That is a rule, not a convenience, because the function does four things in a fixed order and each of them is skipped if you write *Health* yourself:

1. **Authority check.** It returns immediately unless it is running with authority. Damage requested on a client does nothing; the server decides.
2. **Clamp.** Health never goes below 0 or above *MaxHealth*.
3. **Stamina pause.** It calls *UADStaminaComponent::NotifyDamaged*, which is what starts the post-damage regeneration pause described in *StaminaSystem.md*. The stamina component does not watch health; it is told. Setting health directly therefore leaves stamina regenerating straight through a hit, which is exactly the "weightless" feel the pause exists to remove.
4. **Feedback and death.** It fires the hit reaction, and if health has reached 0 it records the death and tells the owning client.

The header comment on *ApplyDamage* adds a replication reason as well. Read it there; this document does not restate replication conditions, which live in *GetLifetimeReplicatedProps* rather than in the header.

## What each RPC is for

| RPC | Direction | Delivery | Why |
|---|---|---|---|
| *MulticastPlayHitReaction* | server to everyone | unreliable | Purely cosmetic. A dropped hit reaction costs nothing, and reliable delivery for something fired on every hit could back up the reliable channel under load |
| *ClientNotifyDeath* | server to owning client | reliable | The owner has to know they died; losing this leaves a player staring at a live-looking character |
| *ServerRequestRespawn* | owning client to server | reliable | Respawn is requested, never assumed. The server restores health to *MaxHealth* |

## Open issues

These are known, deliberate to leave for now, and written down so nobody mistakes them for design:

- **Respawn has no delay.** *RespawnDelaySeconds* (3 by default) is declared and editable but nothing reads it; *ServerRequestRespawn* restores health immediately.
- **Damage to a dead character counts another death.** Health is already 0, the clamp keeps it there, and the `Health <= 0` check passes again, so each further hit increments the death count and sends another death notification.
- ***OnRep_Health* is empty.** Clients receive the value but nothing reacts to the change yet.
