from app.products import IDENTITY, normalized


def propose_groups(per_image_candidates):
    groups, ungrouped = {}, []
    for identifier, candidates in per_image_candidates.items():
        values = []
        for field in (*IDENTITY, "lot"):
            unique = {normalized(candidate.value) for candidate in candidates.get(field, [])}
            if len(unique) != 1 or "" in unique:
                ungrouped.append(
                    {"image_id": identifier, "reason": "产品或批号线索不全、存在冲突，请补拍或填写归组依据"}
                )
                break
            values.append(next(iter(unique)))
        else:
            key = tuple(values)
            groups.setdefault(key, {"image_ids": [], "reason": "名称、规格、厂商和批号一致，仍需人工核对"})
            groups[key]["image_ids"].append(identifier)
    return {"groups": list(groups.values()), "ungrouped": ungrouped}
