import logging
from hamilton import driver,base
import bleak_house.download

dr = (driver.Builder()
      .with_config({"input_path": "html"})
      .with_cache(default_behavior="recompute")
      .with_modules(bleak_house.download).build()
      )
dr.display_all_functions(output_file_path="documents.png")
dr.execute(["html_paths"])