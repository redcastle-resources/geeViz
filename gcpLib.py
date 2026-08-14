"""
   Copyright 2019 Leah Campbell

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""
###################################################################################
#                   GCPLIB.PY
####################################################################################
# Functions for Google Cloud Platform Operations
# Uses gsutil (first section) and google.cloud.storage (second section)
import os, subprocess


#------------------------------------------------------------------------------
#                   USING GSUTIL
#------------------------------------------------------------------------------
# You must have gsutil set up so that the gsutil path is added to your system environment variables in order for this to work.
def download_to_local(bucket_name, trainingDataPath, exportNamePrefix=''):
    """Sync objects from a GCS bucket to a local directory via gsutil.

    Uses ``gsutil -m cp -n -r`` — parallel, no-clobber, recursive. The
    ``-n`` flag skips objects that already exist locally, so re-running
    is cheap.

    Args:
        bucket_name (str): Name of the GCS bucket (no ``gs://`` prefix).
        trainingDataPath (str): Local destination directory.
        exportNamePrefix (str): Object-name prefix filter. Empty string
            (default) downloads the whole bucket.
    """
    syncCommand = 'gsutil.cmd -m cp -n -r gs://'+bucket_name+'/'+exportNamePrefix+'* '+trainingDataPath
    subprocess.Popen(syncCommand, shell=True).wait()


def clearBucket(bucket_name):
    """Delete every object in a GCS bucket via ``gsutil rm -v``.

    Destructive — removes ALL contents of ``gs://<bucket_name>/``. The
    bucket itself is preserved. Requires gsutil on PATH and sufficient
    IAM permissions.

    Args:
        bucket_name (str): Name of the GCS bucket (no ``gs://`` prefix).
    """
    subprocess.Popen('gsutil.cmd rm -v gs://'+bucket_name+'/*').wait()

