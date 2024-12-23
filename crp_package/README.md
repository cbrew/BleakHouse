# Distance-Dependent Chinese Restaurant Process (dd-CRP)

This project implements a Distance-Dependent Chinese Restaurant Process (dd-CRP) with hybrid distances that combine text similarity and structural features like chapter proximity. The example dataset mimics literary sentences inspired by Charles Dickens.

## Features

- **CRP Core**: Implements a flexible dd-CRP clustering algorithm.
- **Decay Functions**: Supports exponential, logistic, and window decay functions for distance falloff.
- **Hybrid Distance**: Combines text similarity and chapter placement for nuanced clustering.
- **Dataset Generator**: Generates Dickens-style sentences with chapter assignments.

## File Structure

```plaintext
crp_project/
├── README.md
├── crp/
│   ├── __init__.py            # Initializes the CRP module
│   ├── core_crp.py            # Core CRP routine
│   ├── decay_functions.py     # Decay functions
│   ├── hybrid_distance.py     # Hybrid distance function
├── data/
│   ├── dataset_generator.py   # Dickens-style dataset generator
├── demo/
│   ├── run_demo.py            # Driver for running the demo
