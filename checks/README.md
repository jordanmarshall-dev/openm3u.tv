# In-country stream checks

The public builder runs on GitHub's servers in the US. A stream locked to another
country answers "forbidden" from there, so it can't be told apart from a dead one.

From inside the country, run:

    openm3u verify ca

and commit the `checks/ca.json` it writes. Builds for the next 14 days drop streams
that failed there and mark the ones that played as checked.
