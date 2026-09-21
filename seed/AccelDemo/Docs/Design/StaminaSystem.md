---
system: Stamina
modules: [AccelDemoCore, AccelDemo]
classes: [UADStaminaComponent, AADCharacter]
status: current
---

# Stamina

Stamina is a 0 to 100 pool held on *UADStaminaComponent*, which every character owns. Sprinting, dodging and interacting all draw from it, and it refills on its own the rest of the time.

## Regeneration

Regen runs at 12 points per second, and it does **not** start again immediately after the character takes damage. There is a 2 second pause first.

That pause is a design decision rather than a technical constraint. Early playtests had regen starting on the same frame as the damage, and testers read the fight as weightless, because there was no moment where a hit felt like it had cost them anything. Two seconds was the shortest pause where people described combat as having weight, and anything past about three seconds made them stop pushing forward. We settled on 2 and have not revisited it.

## Replication

*Stamina* replicates to the owning client only, since nobody else needs to see another player's exact pool. *bExhausted* replicates to everyone, because the exhausted state drives an animation other players can see.