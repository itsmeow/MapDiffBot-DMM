import sys
from .dmm import DMM, split_atom_groups

def diff_turf_or_area(old, new):
    result = []
    diff_notice = None
    oldlen = len(old)
    newlen = len(new)
    if newlen > 0:
        result = [new[newlen - 1]]
    elif oldlen > 0:
        result = [old[oldlen - 1]]
    if newlen > 0 and oldlen > 0 and old[oldlen - 1] != new[newlen - 1]:
        diff_notice = f"{old[oldlen - 1]} TO {new[newlen - 1]}"
    return result, diff_notice

def create_obj(name, desc):
    return f'/obj{{name = "{name}";\n\tdesc = "{desc}"}}'

def create_diff(dmm_old, dmm_new):
    if dmm_old.size != dmm_new.size:
        return 0, None, f"Size changed: {dmm_old.size} to {dmm_new.size}", 0, 0, 0, 0

    diffed_dmm = DMM(dmm_old.key_length, dmm_old.size)
    diffed_dmm.dictionary = dmm_old.dictionary.copy()

    note = f"Key length changed: {dmm_old.key_length} to {dmm_new.key_length}" if dmm_old.key_length != dmm_new.key_length else None
    tiles_changed = 0
    movables_added = 0
    movables_deleted = 0
    turfs_changed = 0
    areas_changed = 0

    for (z, y, x) in dmm_old.coords_zyx:
        coord = x, y, z
        old_tile = dmm_old.get_tile(coord)
        new_tile = dmm_new.get_tile(coord)

        # Nothing
        if old_tile == new_tile:
            diffed_dmm.set_tile(coord, old_tile)
            continue
        tiles_changed += 1
        old_movables, old_turfs, old_areas = split_atom_groups(old_tile)
        new_movables, new_turfs, new_areas = split_atom_groups(new_tile)

        area, area_notice = diff_turf_or_area(old_areas, new_areas)
        turf, turf_notice = diff_turf_or_area(old_turfs, new_turfs)

        movables = new_movables

        if old_movables != new_movables:
            for movable in set(old_movables + new_movables):
                oldcount = old_movables.count(movable)
                newcount = new_movables.count(movable)
                # Added
                if oldcount < newcount:
                    movables_added += newcount - oldcount
                # Deleted
                elif oldcount > newcount:
                    movables_deleted += oldcount - newcount
            movables = [create_obj("---NEW---", "new version's movables below this")] \
                + new_movables \
                + [create_obj("---OLD---", "old version's movables below this")] \
                + old_movables \
                + [create_obj("---END---", "end of movables diff")]
        if not turf_notice is None:
            movables += [create_obj("TURF DIFF: " + turf_notice, turf_notice)]
            turfs_changed += 1
        if not area_notice is None:
            movables += [create_obj("AREA DIFF: " + area_notice, area_notice)]
            areas_changed += 1

        diffed_dmm.set_tile(coord, movables + turf + area)
    if tiles_changed == 0:
        note = "No visible changes"
    return tiles_changed, diffed_dmm, note, movables_added, movables_deleted, turfs_changed, areas_changed

if __name__ == "__main__":
    # python diff.py old.dmm new.dmm diff.dmm
    before = DMM.from_file(sys.argv[1])
    after = DMM.from_file(sys.argv[2])
    tiles_changed, diff_dmm, note, movables_added, movables_deleted, turfs_changed, areas_changed  = create_diff(before, after)
    if not note is None:
        print(note)
    print(f"{tiles_changed} tiles changed")
    print(f"{movables_added} movables added, {movables_deleted} movables deleted")
    print(f"{turfs_changed} turfs changed")
    print(f"{areas_changed} areas changed")
    if tiles_changed > 0:
        out_path = "diff.dmm" if len(sys.argv) < 4 else sys.argv[3]
        diff_dmm.to_file(out_path)
        print(f"Diff saved to: {out_path}")
        