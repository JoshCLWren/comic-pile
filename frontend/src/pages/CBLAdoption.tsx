import React, { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { threadsApi } from '../services/api';
import { queryKeys } from '../query/queryKeys';
import { invalidateAfterQueueMutation } from '../query/cacheEffects';
import { queryClient } from '../query/queryClient';

const CBLAdoption = () => {
  const [selectedCBL, setSelectedCBL] = useState(null);
  const [adoptionPlan, setAdoptionPlan] = useState(null);
  const [selections, setSelections] = useState({});

  const { data: cbls, isPending: isLoadingCBLs } = useQuery({
    queryKey: queryKeys.cbl.list(),
    queryFn: threadsApi.listCBLs,
  });

  const { mutate: previewAdoption } = useMutation({
    mutationFn: threadsApi.previewAdoption,
    onSuccess: (data) => setAdoptionPlan(data),
  });

  const { mutate: adoptCBL } = useMutation({
    mutationFn: threadsApi.adoptCBL,
    onSuccess: () => {
      invalidateAfterQueueMutation(queryClient);
      // Redirect to the new reading order
    },
  });

  const handleSelectCBL = (cblId) => {
    setSelectedCBL(cblId);
    previewAdoption(cblId);
  };

const handleToggleSeries = (seriesId: number, exclude: boolean) => {
     setSelections((prev) => ({ ...prev, [seriesId]: exclude }));
     // Update adoption plan based on selections
   };

   const handleToggleEntry = (_entryId: number, exclude: boolean) => {
     setSelections((prev) => ({ ...prev, [_entryId]: exclude }));
   };

   const isEntryExcluded = (entry: { id: number; seriesId: number }) => {
     const entryExcluded = selections[entry.id];
     if (entryExcluded !== undefined) {
       return entryExcluded;
     }
     return selections[entry.seriesId]?.exclude ?? false;
   };

  const handleAdopt = () => {
    adoptCBL({ cblId: selectedCBL, selections });
  };

  if (isLoadingCBLs) return <div>Loading CBLs...</div>;

  return (
    <div className="p-4">
      <h1 className="text-2xl font-bold mb-4">CBL Adoption</h1>
      <div className="mb-4">
        <h2 className="text-xl font-semibold mb-2">Select CBL</h2>
<select
           className="border p-2 rounded-lg w-full"
           onChange={(e) => handleSelectCBL(e.target.value)}
         >
          <option value="">Choose a CBL</option>
          {cbls?.map((cbl) => (
            <option key={cbl.id} value={cbl.id}>
              {cbl.name}
            </option>
          ))}
        </select>
      </div>
      {selectedCBL && (
        <div>
          <h2 className="text-xl font-semibold mb-2">Preview and Adjust</h2>
          <div className="mb-4">
            <h3 className="text-lg font-medium mb-2">Source Order</h3>
            {adoptionPlan?.entries.map((entry) => (
               <div key={entry.id} className="flex justify-between items-center p-2 border-b border-gray-200">
                <span>{entry.title}</span>
                <div>
<label>
                   <input
                     type="checkbox"
                     checked={!isEntryExcluded(entry)}
                     onChange={(e) => handleToggleEntry(entry.id, !e.target.checked)}
                   />
                     Include
                   </label>
                </div>
              </div>
            ))}
          </div>
          <div className="mb-4">
            <h3 className="text-lg font-medium mb-2">Series Exclusions</h3>
            {adoptionPlan?.series.map((series) => (
              <div key={series.id} className="flex justify-between items-center p-2 border-b">
                <span>{series.name}</span>
                <button
                  onClick={() => handleToggleSeries(series.id, !selections[series.id]?.exclude)}
                  className={`px-3 py-1 rounded ${
                    selections[series.id]?.exclude ? 'bg-red-500 text-white' : 'bg-green-500 text-white'
                  }`}
                >
                  {selections[series.id]?.exclude ? 'Excluded' : 'Included'}
                </button>
              </div>
            ))}
          </div>
          <div className="mb-4">
            <h3 className="text-lg font-medium mb-2">Reconciliation</h3>
            {/* Reconciliation UI for ambiguous entries */}
          </div>
          <div className="mb-4">
            <h3 className="text-lg font-medium mb-2">Review Changes</h3>
            <p>Existing comics reused: {adoptionPlan?.existingCount}</p>
            <p>Missing comics to create: {adoptionPlan?.missingCount}</p>
            <p>Excluded entries: {adoptionPlan?.excludedCount}</p>
            <p>Unresolved entries: {adoptionPlan?.unresolvedCount}</p>
          </div>
          <button
            onClick={handleAdopt}
            className="bg-blue-500 text-white px-4 py-2 rounded"
          >
            Adopt CBL
          </button>
        </div>
      )}
    </div>
  );
};

export default CBLAdoption;