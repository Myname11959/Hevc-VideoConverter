# test_opts_clean.py


def clean_opts(opts):
    cleaned = []
    skip_next = False
    for i, item in enumerate(opts):
        if skip_next:
            skip_next = False
            continue
        if item.startswith("-"):  # è un flag
            # Controlla se ha un valore associato
            if i + 1 < len(opts):
                value = opts[i + 1]
                # Se il valore è vuoto, Nessuno o None → scarta
                if value in ("", "Nessuno", None):
                    skip_next = True
                    continue
                # Altrimenti tieni entrambi
                cleaned.extend([item, value])
                skip_next = True
            else:
                cleaned.append(item)
        else:
            cleaned.append(item)
    return cleaned


# Test con una lista opzioni simulata
opts = ["-b:a", "128k", "-ac", "2", "-b:v", "Nessuno", "-crf", "", "-preset", "faster"]

print("Prima:", opts)
print("Dopo :", clean_opts(opts))
